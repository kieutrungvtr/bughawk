"""CLI entry point for BugHawk.

This module provides the command-line interface for BugHawk using Click
and Rich for beautiful, hawk-themed output.
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from bughawk import __version__
from bughawk.core.config import (
    BugHawkConfig,
    ConfigurationError,
    load_config,
    validate_config_for_fetch,
    validate_config_for_fix,
)
from bughawk.core.models import IssueSeverity
from bughawk.sentry.client import (
    SentryAPIError,
    SentryAuthenticationError,
    SentryClient,
    SentryNotFoundError,
)

# Hawk-themed color palette
HAWK_THEME = Theme(
    {
        "hawk.gold": "bold #D4A017",
        "hawk.amber": "#FFBF00",
        "hawk.bronze": "#CD7F32",
        "hawk.brown": "#8B4513",
        "hawk.feather": "#C4A484",
        "hawk.sky": "#87CEEB",
        "hawk.success": "bold green",
        "hawk.error": "bold red",
        "hawk.warning": "bold yellow",
        "hawk.info": "bold #D4A017",
        "hawk.dim": "dim",
    }
)

console = Console(theme=HAWK_THEME)

# Hawk emoji for branding
HAWK = "🦅"

# ASCII Art Logo
HAWK_LOGO = r"""
    ,_   _,
    |'\_/'|
   / (o o) \
  | "====" |    BugHawk
   \ ____ /     Automated Bug Hunting & Fixing
    |    |
    |    |
"""


def print_logo() -> None:
    """Print the ASCII hawk logo."""
    console.print(f"[hawk.gold]{HAWK_LOGO}[/hawk.gold]")


def print_banner(with_logo: bool = False) -> None:
    """Print the BugHawk banner."""
    if with_logo:
        print_logo()
    else:
        banner = Text()
        banner.append(f"{HAWK} BugHawk", style="hawk.gold")
        banner.append(f" v{__version__}", style="hawk.feather")
        banner.append(" - Automated Bug Hunting & Fixing", style="hawk.dim")
        console.print(banner)


def print_error(message: str, hint: Optional[str] = None) -> None:
    """Print an error message with optional hint."""
    console.print(f"\n[hawk.error]{HAWK} Error:[/hawk.error] {message}")
    if hint:
        console.print(f"[hawk.dim]Hint: {hint}[/hawk.dim]")


def print_success(message: str) -> None:
    """Print a success message."""
    console.print(f"\n[hawk.success]{HAWK} {message}[/hawk.success]")


def print_warning(message: str) -> None:
    """Print a warning message."""
    console.print(f"\n[hawk.warning]{HAWK} {message}[/hawk.warning]")


def print_info(message: str) -> None:
    """Print an info message."""
    console.print(f"\n[hawk.info]{HAWK} {message}[/hawk.info]")


def get_config_safe() -> Optional[BugHawkConfig]:
    """Load configuration with error handling."""
    try:
        return load_config()
    except ConfigurationError as e:
        print_error(f"Configuration error: {e}")
        return None


def create_sentry_client(config: BugHawkConfig) -> Optional[SentryClient]:
    """Create a SentryClient with error handling."""
    try:
        validate_config_for_fetch(config)
    except ConfigurationError as e:
        print_error(str(e))
        console.print("\n[hawk.dim]To configure BugHawk, run:[/hawk.dim]")
        console.print("  [hawk.amber]bughawk init[/hawk.amber]")
        console.print("\n[hawk.dim]Or set environment variables:[/hawk.dim]")
        console.print("  [hawk.feather]export BUGHAWK_SENTRY_AUTH_TOKEN=your_token[/hawk.feather]")
        console.print("  [hawk.feather]export BUGHAWK_SENTRY_ORG=your_org[/hawk.feather]")
        console.print("  [hawk.feather]export BUGHAWK_SENTRY_PROJECTS=project1,project2[/hawk.feather]")
        return None

    from bughawk.core.config import Settings

    settings = Settings(
        sentry_auth_token=config.sentry.auth_token,
        sentry_org=config.sentry.org,
        sentry_project=config.sentry.projects[0] if config.sentry.projects else "",
    )

    return SentryClient(settings=settings, base_url=config.sentry.base_url)


def format_count(count: int) -> str:
    """Format a count with color based on severity."""
    if count >= 1000:
        return f"[bold red]{count:,}[/bold red]"
    elif count >= 100:
        return f"[yellow]{count:,}[/yellow]"
    elif count >= 10:
        return f"[hawk.amber]{count:,}[/hawk.amber]"
    else:
        return f"[hawk.feather]{count:,}[/hawk.feather]"


def format_severity(severity: str) -> str:
    """Format severity level with appropriate color."""
    colors = {
        "fatal": "bold red",
        "error": "red",
        "warning": "yellow",
        "info": "blue",
        "debug": "dim",
    }
    color = colors.get(severity.lower(), "white")
    return f"[{color}]{severity.upper()}[/{color}]"


def format_confidence(score: float) -> str:
    """Format confidence score with color."""
    if score >= 0.8:
        return f"[bold green]{score:.2f}[/bold green]"
    elif score >= 0.6:
        return f"[green]{score:.2f}[/green]"
    elif score >= 0.4:
        return f"[yellow]{score:.2f}[/yellow]"
    else:
        return f"[red]{score:.2f}[/red]"


def confirm_action(message: str, default: bool = False) -> bool:
    """Ask for user confirmation."""
    suffix = " [Y/n]" if default else " [y/N]"
    response = console.input(f"[hawk.amber]{message}{suffix}[/hawk.amber] ")
    if not response:
        return default
    return response.lower() in ("y", "yes")


# CLI Group and Commands


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="BugHawk")
@click.option("--logo", is_flag=True, help="Show ASCII art logo")
@click.pass_context
def main(ctx: click.Context, logo: bool) -> None:
    """BugHawk - Automated Bug Hunting & Fixing.

    A CLI tool that connects to Sentry, analyzes issues, and proposes fixes.

    \b
    Quick start:
      bughawk init              Create configuration file
      bughawk config test       Verify Sentry connection
      bughawk list-issues       List unresolved issues
      bughawk fix ISSUE_ID      Fix a specific issue
      bughawk hunt              Hunt all matching bugs
    """
    if ctx.invoked_subcommand is None:
        print_banner(with_logo=logo)
        console.print("\n[hawk.dim]Run [hawk.amber]bughawk --help[/hawk.amber] for available commands.[/hawk.dim]")


# =============================================================================
# Fix Commands
# =============================================================================


@main.command("fix")
@click.argument("issue_id")
@click.option(
    "--repo-url",
    "-r",
    help="Repository URL (extracted from issue if not provided)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show proposed fix without creating PR",
)
@click.option(
    "--auto-merge",
    is_flag=True,
    help="Auto-merge if confidence > 0.9",
)
@click.option(
    "--skip-tests",
    is_flag=True,
    help="Skip running tests during validation",
)
@click.option(
    "--min-confidence",
    "-c",
    type=float,
    default=0.6,
    help="Minimum confidence to create PR (default: 0.6)",
)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Skip confirmation prompts",
)
@click.option(
    "--llm-provider",
    "-p",
    type=click.Choice(["openai", "anthropic", "claude", "azure", "gemini", "ollama", "groq", "mistral", "cohere"]),
    help="LLM provider to use for fix generation (overrides config)",
)
@click.option(
    "--llm-model",
    "-m",
    help="Specific model to use (e.g., gpt-4, claude-sonnet-4-20250514)",
)
def fix_issue(
    issue_id: str,
    repo_url: Optional[str],
    dry_run: bool,
    auto_merge: bool,
    skip_tests: bool,
    min_confidence: float,
    force: bool,
    llm_provider: Optional[str],
    llm_model: Optional[str],
) -> None:
    """Fix a specific Sentry issue.

    ISSUE_ID is the Sentry issue ID to fix.

    \b
    Examples:
      bughawk fix 12345                    Fix issue 12345
      bughawk fix 12345 --dry-run          Preview fix without creating PR
      bughawk fix 12345 -c 0.8             Only create PR if confidence >= 0.8
      bughawk fix 12345 --repo-url URL     Specify repository URL
    """
    print_banner()

    config = get_config_safe()
    if not config:
        sys.exit(1)

    try:
        validate_config_for_fix(config)
    except ConfigurationError as e:
        print_error(str(e))
        sys.exit(1)

    # Import orchestrator
    from bughawk.core.orchestrator import Orchestrator, OrchestratorError

    console.print(Panel(
        f"[hawk.gold]{HAWK} The Hunt Begins[/hawk.gold]\n\n"
        f"Target: [cyan]{issue_id}[/cyan]\n"
        f"Mode: [yellow]{'Dry Run' if dry_run else 'Live'}[/yellow]\n"
        f"Min Confidence: [green]{min_confidence}[/green]",
        border_style="hawk.bronze",
    ))

    if not dry_run and not force:
        if not confirm_action("Proceed with fix generation?", default=True):
            print_info("Hunt cancelled")
            return

    try:
        orchestrator = Orchestrator(
            config=config,
            confidence_threshold=min_confidence,
            dry_run=dry_run,
        )

        if dry_run:
            fix_proposal = orchestrator.dry_run_issue(issue_id, repo_url=repo_url)
            if fix_proposal:
                _display_fix_proposal(fix_proposal)
            else:
                print_warning("Could not generate a fix for this issue")
        else:
            pr_url = orchestrator.process_issue(issue_id, repo_url=repo_url)

            if pr_url:
                print_success(f"Fix submitted!")
                console.print(f"\n[hawk.amber]Pull Request:[/hawk.amber] [link={pr_url}]{pr_url}[/link]")

                if auto_merge:
                    state = orchestrator._hunt_states.get(issue_id)
                    if state and state.fix_proposal:
                        if state.fix_proposal.confidence_score >= 0.9:
                            console.print("\n[hawk.gold]Auto-merge requested (confidence >= 0.9)[/hawk.gold]")
                            # Note: Auto-merge would require additional GitHub API calls
                            console.print("[hawk.dim]Auto-merge not yet implemented[/hawk.dim]")
                        else:
                            console.print(f"\n[hawk.dim]Confidence {state.fix_proposal.confidence_score:.2f} < 0.9, skipping auto-merge[/hawk.dim]")
            else:
                # Check state for reason
                state = orchestrator._hunt_states.get(issue_id)
                if state:
                    if state.result and state.result.value == "low_confidence":
                        print_warning(f"Confidence too low for PR creation")
                    elif state.result and state.result.value == "validation_failed":
                        print_error("Fix validation failed")
                    elif state.error:
                        print_error(f"Hunt failed: {state.error}")
                else:
                    print_warning("No fix was generated")

    except OrchestratorError as e:
        print_error(str(e))
        sys.exit(1)
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        if config.debug:
            console.print_exception()
        sys.exit(1)


@main.command("hunt")
@click.option(
    "--limit",
    "-l",
    type=int,
    default=10,
    help="Maximum number of issues to process (default: 10)",
)
@click.option(
    "--min-confidence",
    "-c",
    type=float,
    default=0.6,
    help="Minimum confidence to create PR (default: 0.6)",
)
@click.option(
    "--project",
    "-p",
    help="Limit to specific Sentry project",
)
@click.option(
    "--repo-url",
    "-r",
    help="Repository URL for all issues",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show proposed fixes without creating PRs",
)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Skip confirmation prompts",
)
def hunt_bugs(
    limit: int,
    min_confidence: float,
    project: Optional[str],
    repo_url: Optional[str],
    dry_run: bool,
    force: bool,
) -> None:
    """Hunt all matching bugs from Sentry.

    The hawk takes flight to hunt down bugs across your projects.

    \b
    Examples:
      bughawk hunt                         Hunt up to 10 issues
      bughawk hunt --limit 5               Hunt up to 5 issues
      bughawk hunt -p my-project           Hunt issues from specific project
      bughawk hunt --dry-run               Preview without creating PRs
    """
    print_banner(with_logo=True)

    config = get_config_safe()
    if not config:
        sys.exit(1)

    try:
        validate_config_for_fix(config)
    except ConfigurationError as e:
        print_error(str(e))
        sys.exit(1)

    # Override project if specified
    if project:
        config.sentry.projects = [project]

    console.print(Panel(
        f"[hawk.gold]{HAWK} The Great Hunt[/hawk.gold]\n\n"
        f"Projects: [cyan]{', '.join(config.sentry.projects)}[/cyan]\n"
        f"Limit: [yellow]{limit}[/yellow] issues\n"
        f"Min Confidence: [green]{min_confidence}[/green]\n"
        f"Mode: [{'yellow' if dry_run else 'green'}]{'Dry Run' if dry_run else 'Live'}[/]",
        border_style="hawk.bronze",
    ))

    if not dry_run and not force:
        if not confirm_action(f"Hunt up to {limit} bugs?", default=True):
            print_info("Hunt cancelled")
            return

    from bughawk.core.orchestrator import Orchestrator

    try:
        orchestrator = Orchestrator(
            config=config,
            confidence_threshold=min_confidence,
            dry_run=dry_run,
        )

        report = orchestrator.process_all_issues(
            repo_url=repo_url,
            max_issues=limit,
        )

        # Summary is displayed by orchestrator
        console.print(f"\n[hawk.dim]Report saved to: {config.output_dir / 'reports'}[/hawk.dim]")

    except Exception as e:
        print_error(f"Hunt failed: {e}")
        if config.debug:
            console.print_exception()
        sys.exit(1)


@main.command("analyze")
@click.argument("issue_id")
@click.option(
    "--repo-url",
    "-r",
    help="Repository URL (extracted from issue if not provided)",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Show detailed analysis",
)
def analyze_issue(issue_id: str, repo_url: Optional[str], verbose: bool) -> None:
    """Analyze a Sentry issue without creating a fix.

    Shows root cause analysis, suggested approach, and confidence score.

    ISSUE_ID is the Sentry issue ID to analyze.
    """
    print_banner()

    config = get_config_safe()
    if not config:
        sys.exit(1)

    client = create_sentry_client(config)
    if not client:
        sys.exit(1)

    console.print(f"\n[hawk.gold]{HAWK} Analyzing issue {issue_id}...[/hawk.gold]")

    try:
        # Fetch issue details
        with Progress(
            SpinnerColumn(),
            TextColumn("[hawk.gold]Fetching issue details...[/hawk.gold]"),
            console=console,
        ) as progress:
            progress.add_task("fetch", total=None)
            issue = client.get_issue_details(issue_id)
            events = client.get_issue_events(issue_id, limit=1, full=True)

        # Display issue info
        console.print(Panel(
            f"[bold]{issue.title}[/bold]\n\n"
            f"[hawk.dim]ID:[/] {issue.id}\n"
            f"[hawk.dim]Culprit:[/] {issue.culprit or 'Unknown'}\n"
            f"[hawk.dim]Occurrences:[/] {issue.count:,}\n"
            f"[hawk.dim]Level:[/] {format_severity(issue.level.value if hasattr(issue.level, 'value') else str(issue.level))}",
            title=f"{HAWK} Issue Details",
            border_style="hawk.bronze",
        ))

        # Pattern matching analysis
        from bughawk.analyzer.pattern_matcher import PatternMatcher

        matcher = PatternMatcher()

        # Extract exception info from events
        exception_type = ""
        exception_value = ""
        if events:
            for entry in events[0].get("entries", []):
                if entry.get("type") == "exception":
                    values = entry.get("data", {}).get("values", [])
                    if values:
                        exception_type = values[0].get("type", "")
                        exception_value = values[0].get("value", "")
                        break

        pattern_match = matcher.match_pattern(
            exception_type=exception_type,
            message=issue.title,
            code_snippet="",
        )

        # Analysis panel
        analysis_text = Text()

        if pattern_match:
            analysis_text.append("Pattern Match: ", style="hawk.dim")
            analysis_text.append(f"{pattern_match.pattern.name}\n", style="hawk.gold")
            analysis_text.append("Confidence: ", style="hawk.dim")
            analysis_text.append(f"{pattern_match.confidence:.2f}\n\n", style="green" if pattern_match.confidence >= 0.6 else "yellow")

            analysis_text.append("Common Causes:\n", style="hawk.amber")
            for cause in pattern_match.pattern.common_causes[:3]:
                analysis_text.append(f"  • {cause}\n", style="hawk.feather")

            analysis_text.append("\nTypical Fixes:\n", style="hawk.amber")
            for fix in pattern_match.pattern.typical_fixes[:3]:
                analysis_text.append(f"  • {fix}\n", style="hawk.feather")

            if pattern_match.suggested_fix:
                analysis_text.append("\nSuggested Approach:\n", style="hawk.amber")
                analysis_text.append(f"  {pattern_match.suggested_fix}\n", style="white")
        else:
            analysis_text.append("No matching pattern found.\n\n", style="hawk.dim")
            analysis_text.append("This issue may require LLM analysis for a fix.\n", style="hawk.feather")
            analysis_text.append("Run ", style="hawk.dim")
            analysis_text.append(f"bughawk fix {issue_id} --dry-run", style="hawk.amber")
            analysis_text.append(" for detailed fix proposal.\n", style="hawk.dim")

        console.print(Panel(
            analysis_text,
            title=f"{HAWK} Analysis",
            border_style="hawk.bronze",
        ))

        # Verbose output
        if verbose and exception_type:
            console.print(Panel(
                f"[bold red]{exception_type}[/bold red]: {exception_value}",
                title="Exception",
                border_style="red",
            ))

    except SentryNotFoundError:
        print_error(f"Issue not found: {issue_id}")
        sys.exit(1)
    except SentryAPIError as e:
        print_error(f"API error: {e.message}")
        sys.exit(1)


# =============================================================================
# Status Command
# =============================================================================


@main.command("status")
@click.option(
    "--days",
    "-d",
    type=int,
    default=7,
    help="Show statistics for last N days (default: 7)",
)
def show_status(days: int) -> None:
    """Show hunting statistics and recent activity.

    Displays summary of recent automated fixes, PR status, and success rate.
    """
    print_banner()

    config = get_config_safe()
    if not config:
        sys.exit(1)

    console.print(Panel(
        f"[hawk.gold]{HAWK} Hunting Statistics[/hawk.gold]",
        border_style="hawk.bronze",
    ))

    # Load recent hunt reports
    reports_dir = config.output_dir / "reports"
    states_dir = config.output_dir / "state"

    total_hunts = 0
    total_success = 0
    total_failed = 0
    total_low_confidence = 0
    prs_created: List[str] = []
    recent_issues: List[Dict[str, Any]] = []

    cutoff = datetime.now() - timedelta(days=days)

    # Read hunt states
    if states_dir.exists():
        for state_file in states_dir.glob("hunt_*.json"):
            try:
                with open(state_file) as f:
                    state_data = json.load(f)

                started = datetime.fromisoformat(state_data.get("started_at", ""))
                if started >= cutoff:
                    total_hunts += 1
                    result = state_data.get("result")

                    if result == "success":
                        total_success += 1
                        if state_data.get("pr_url"):
                            prs_created.append(state_data["pr_url"])
                    elif result == "low_confidence":
                        total_low_confidence += 1
                    elif result in ("error", "validation_failed"):
                        total_failed += 1

                    recent_issues.append({
                        "id": state_data.get("issue_id"),
                        "result": result,
                        "pr_url": state_data.get("pr_url"),
                        "date": started,
                    })
            except (json.JSONDecodeError, KeyError, ValueError):
                continue

    # Statistics table
    stats_table = Table(
        title=f"Last {days} Days",
        border_style="hawk.bronze",
        show_header=False,
    )
    stats_table.add_column("Metric", style="hawk.dim")
    stats_table.add_column("Value", justify="right")

    stats_table.add_row("Total Hunts", f"[hawk.amber]{total_hunts}[/]")
    stats_table.add_row("Successful Fixes", f"[green]{total_success}[/]")
    stats_table.add_row("Low Confidence", f"[yellow]{total_low_confidence}[/]")
    stats_table.add_row("Failed", f"[red]{total_failed}[/]")

    if total_hunts > 0:
        success_rate = (total_success / total_hunts) * 100
        stats_table.add_row("Success Rate", f"[{'green' if success_rate >= 50 else 'yellow'}]{success_rate:.1f}%[/]")

    stats_table.add_row("PRs Created", f"[hawk.gold]{len(prs_created)}[/]")

    console.print(stats_table)

    # Recent activity
    if recent_issues:
        recent_issues.sort(key=lambda x: x["date"], reverse=True)

        activity_table = Table(
            title="Recent Activity",
            border_style="hawk.bronze",
        )
        activity_table.add_column("Issue", style="hawk.feather")
        activity_table.add_column("Result", justify="center")
        activity_table.add_column("Date", style="hawk.dim")
        activity_table.add_column("PR", max_width=40)

        for item in recent_issues[:10]:
            result_display = {
                "success": "[green]Success[/]",
                "low_confidence": "[yellow]Low Conf[/]",
                "error": "[red]Error[/]",
                "validation_failed": "[red]Invalid[/]",
            }.get(item["result"] or "", "[dim]Unknown[/]")

            pr_display = ""
            if item.get("pr_url"):
                pr_display = f"[link={item['pr_url']}]View PR[/link]"

            activity_table.add_row(
                item["id"],
                result_display,
                item["date"].strftime("%Y-%m-%d %H:%M"),
                pr_display,
            )

        console.print()
        console.print(activity_table)

    if not total_hunts:
        console.print("\n[hawk.dim]No hunting activity in the last {days} days.[/hawk.dim]")
        console.print("[hawk.dim]Run [hawk.amber]bughawk hunt[/hawk.amber] to start hunting bugs![/hawk.dim]")


# =============================================================================
# List Issues Command
# =============================================================================


@main.command("list-issues")
@click.option(
    "--project",
    "-p",
    help="Sentry project slug (uses first configured project if not specified)",
)
@click.option(
    "--severity",
    "-s",
    type=click.Choice(["debug", "info", "warning", "error", "fatal"], case_sensitive=False),
    help="Filter by severity level",
)
@click.option(
    "--limit",
    "-l",
    default=25,
    type=int,
    help="Maximum number of issues to display (default: 25)",
)
@click.option(
    "--all-pages",
    is_flag=True,
    help="Fetch all pages of results (may be slow)",
)
def list_issues(
    project: Optional[str],
    severity: Optional[str],
    limit: int,
    all_pages: bool,
) -> None:
    """List unresolved issues from Sentry.

    Displays issues in a formatted table with counts, severity, and timestamps.
    """
    print_banner()

    config = get_config_safe()
    if not config:
        sys.exit(1)

    client = create_sentry_client(config)
    if not client:
        sys.exit(1)

    target_project = project or (config.sentry.projects[0] if config.sentry.projects else None)
    if not target_project:
        print_error("No project specified and none configured.")
        sys.exit(1)

    filters: Dict[str, str] = {"query": "is:unresolved"}
    if severity:
        filters["query"] += f" level:{severity}"

    with Progress(
        SpinnerColumn(),
        TextColumn(f"[hawk.gold]{HAWK} Hunting for issues...[/hawk.gold]"),
        console=console,
    ) as progress:
        progress.add_task("fetch", total=None)

        try:
            max_pages = None if all_pages else (limit // 100) + 1
            issues = client.get_issues(
                project=target_project,
                filters=filters,
                organization=config.sentry.org,
                max_pages=max_pages,
            )
        except SentryAuthenticationError:
            print_error(
                "Authentication failed. Your Sentry token may be invalid or expired.",
                hint="Generate a new token at https://sentry.io/settings/account/api/auth-tokens/",
            )
            sys.exit(1)
        except SentryAPIError as e:
            print_error(f"Failed to fetch issues: {e.message}")
            sys.exit(1)

    if not issues:
        print_info("No unresolved issues found.")
        return

    display_issues = issues[:limit]

    table = Table(
        title=f"{HAWK} Issues in [hawk.amber]{target_project}[/hawk.amber]",
        title_style="hawk.gold",
        border_style="hawk.bronze",
        header_style="hawk.gold",
        show_lines=True,
    )

    table.add_column("ID", style="hawk.feather", width=12)
    table.add_column("Title", style="white", max_width=50)
    table.add_column("Level", justify="center", width=8)
    table.add_column("Count", justify="right", width=8)
    table.add_column("Last Seen", style="hawk.dim", width=20)

    for issue in display_issues:
        last_seen = issue.last_seen.strftime("%Y-%m-%d %H:%M") if issue.last_seen else "Unknown"

        table.add_row(
            issue.id,
            issue.title[:50] + "..." if len(issue.title) > 50 else issue.title,
            format_severity(issue.level.value if isinstance(issue.level, IssueSeverity) else str(issue.level)),
            format_count(issue.count),
            last_seen,
        )

    console.print()
    console.print(table)

    if len(issues) > limit:
        console.print(
            f"\n[hawk.dim]Showing {limit} of {len(issues)} issues. "
            f"Use --limit to see more.[/hawk.dim]"
        )

    console.print(f"\n[hawk.dim]To fix an issue: [hawk.amber]bughawk fix ISSUE_ID[/hawk.amber][/hawk.dim]")


@main.command("show-issue")
@click.argument("issue_id")
@click.option(
    "--events",
    "-e",
    default=5,
    type=int,
    help="Number of recent events to show (default: 5)",
)
def show_issue(issue_id: str, events: int) -> None:
    """Show detailed information about a specific issue.

    ISSUE_ID is the Sentry issue ID to display.
    """
    print_banner()

    config = get_config_safe()
    if not config:
        sys.exit(1)

    client = create_sentry_client(config)
    if not client:
        sys.exit(1)

    with Progress(
        SpinnerColumn(),
        TextColumn(f"[hawk.gold]{HAWK} Fetching issue details...[/hawk.gold]"),
        console=console,
    ) as progress:
        progress.add_task("fetch", total=None)

        try:
            issue = client.get_issue_details(issue_id)
            issue_events = client.get_issue_events(issue_id, limit=events, full=True)
        except SentryNotFoundError:
            print_error(f"Issue not found: {issue_id}")
            sys.exit(1)
        except SentryAuthenticationError:
            print_error(
                "Authentication failed. Your Sentry token may be invalid or expired.",
                hint="Generate a new token at https://sentry.io/settings/account/api/auth-tokens/",
            )
            sys.exit(1)
        except SentryAPIError as e:
            print_error(f"Failed to fetch issue: {e.message}")
            sys.exit(1)

    # Issue header panel
    header = Text()
    header.append(f"{issue.title}\n\n", style="bold white")
    header.append("ID: ", style="hawk.dim")
    header.append(f"{issue.id}\n", style="hawk.feather")
    header.append("Culprit: ", style="hawk.dim")
    header.append(f"{issue.culprit or 'Unknown'}\n", style="hawk.feather")
    header.append("Status: ", style="hawk.dim")
    header.append(f"{issue.status.value if hasattr(issue.status, 'value') else issue.status}\n", style="hawk.amber")

    console.print()
    console.print(Panel(header, title=f"{HAWK} Issue Details", border_style="hawk.bronze"))

    # Stats table
    stats_table = Table(show_header=False, border_style="hawk.bronze", box=None)
    stats_table.add_column("Label", style="hawk.dim")
    stats_table.add_column("Value", style="hawk.feather")

    level_value = issue.level.value if isinstance(issue.level, IssueSeverity) else str(issue.level)
    stats_table.add_row("Level", format_severity(level_value))
    stats_table.add_row("Occurrences", format_count(issue.count))
    stats_table.add_row(
        "First Seen",
        issue.first_seen.strftime("%Y-%m-%d %H:%M:%S") if issue.first_seen else "Unknown",
    )
    stats_table.add_row(
        "Last Seen",
        issue.last_seen.strftime("%Y-%m-%d %H:%M:%S") if issue.last_seen else "Unknown",
    )

    console.print()
    console.print(Panel(stats_table, title="Statistics", border_style="hawk.bronze"))

    # Tags
    if issue.tags:
        tags_text = Text()
        for key, value in issue.tags.items():
            tags_text.append(f"{key}: ", style="hawk.dim")
            tags_text.append(f"{value}  ", style="hawk.feather")

        console.print()
        console.print(Panel(tags_text, title="Tags", border_style="hawk.bronze"))

    # Stack trace from first event
    if issue_events:
        first_event = issue_events[0]
        entries = first_event.get("entries", [])

        for entry in entries:
            if entry.get("type") == "exception":
                values = entry.get("data", {}).get("values", [])
                if values:
                    exc = values[0]
                    exc_type = exc.get("type", "Exception")
                    exc_value = exc.get("value", "")

                    console.print()
                    console.print(
                        Panel(
                            f"[bold red]{exc_type}[/bold red]: {exc_value}",
                            title="Exception",
                            border_style="red",
                        )
                    )

                    frames = exc.get("stacktrace", {}).get("frames", [])
                    if frames:
                        stack_text = Text()
                        for frame in reversed(frames[-10:]):
                            filename = frame.get("filename", "unknown")
                            lineno = frame.get("lineNo", "?")
                            function = frame.get("function", "unknown")
                            in_app = frame.get("inApp", False)

                            if in_app:
                                stack_text.append(f"  {filename}", style="hawk.amber")
                            else:
                                stack_text.append(f"  {filename}", style="hawk.dim")

                            stack_text.append(f":{lineno}", style="hawk.feather")
                            stack_text.append(f" in {function}\n", style="white")

                            context_line = frame.get("context_line") or frame.get("contextLine")
                            if context_line:
                                stack_text.append(f"    {context_line.strip()}\n", style="hawk.dim")

                        console.print()
                        console.print(
                            Panel(
                                stack_text,
                                title="Stack Trace (most recent first)",
                                border_style="hawk.bronze",
                            )
                        )
                    break

    # Action hint
    console.print(f"\n[hawk.dim]To fix this issue: [hawk.amber]bughawk fix {issue_id}[/hawk.amber][/hawk.dim]")


# =============================================================================
# Config Commands
# =============================================================================


@main.group("config")
def config_group() -> None:
    """Configuration management commands."""
    pass


@config_group.command("init")
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Overwrite existing configuration file",
)
def config_init(force: bool) -> None:
    """Initialize BugHawk configuration file.

    Creates a .bughawk.yml configuration file in the current directory
    with example settings that you can customize.
    """
    print_banner()

    config_path = Path.cwd() / ".bughawk.yml"

    if config_path.exists() and not force:
        print_warning(f"Configuration file already exists: {config_path}")
        console.print("[hawk.dim]Use --force to overwrite.[/hawk.dim]")
        return

    config_content = """\
# BugHawk Configuration File
# Automated Bug Hunting & Fixing

sentry:
  # Get your token at: https://sentry.io/settings/account/api/auth-tokens/
  auth_token: ""
  org: ""
  projects:
    - my-project
  base_url: "https://sentry.io/api/0"

filters:
  min_events: 1
  severity_levels:
    - error
    - fatal
  max_age_days: 30
  ignored_issues: []

llm:
  provider: openai  # openai, anthropic, or azure
  api_key: ""
  model: "gpt-4"
  max_tokens: 4096
  temperature: 0.1

git:
  provider: github  # github, gitlab, or bitbucket
  token: ""
  branch_prefix: "bughawk/fix-"
  auto_pr: true
  base_branch: "main"

debug: false
output_dir: ".bughawk"
"""

    try:
        config_path.write_text(config_content)
        print_success(f"Configuration file created: {config_path}")
        console.print("\n[hawk.dim]Next steps:[/hawk.dim]")
        console.print("  1. Edit [hawk.amber].bughawk.yml[/hawk.amber] with your settings")
        console.print("  2. Add your Sentry auth token")
        console.print("  3. Add your LLM API key")
        console.print("  4. Add your Git provider token")
        console.print("  5. Run [hawk.amber]bughawk config test[/hawk.amber] to verify")
    except OSError as e:
        print_error(f"Failed to create configuration file: {e}")
        sys.exit(1)


@config_group.command("test")
def config_test() -> None:
    """Test Sentry connection and configuration.

    Verifies that your configuration is valid and can connect to Sentry.
    """
    print_banner()

    console.print("\n[hawk.dim]Checking configuration...[/hawk.dim]")

    config = get_config_safe()
    if not config:
        sys.exit(1)

    # Check required fields
    issues = []
    if not config.sentry.auth_token:
        issues.append("Sentry auth token is not set")
    if not config.sentry.org:
        issues.append("Sentry organization is not set")
    if not config.sentry.projects:
        issues.append("No Sentry projects configured")

    if issues:
        print_error("Configuration incomplete:")
        for issue in issues:
            console.print(f"  [hawk.dim]•[/hawk.dim] {issue}")
        console.print("\n[hawk.dim]Run [hawk.amber]bughawk config init[/hawk.amber] to create a configuration file.[/hawk.dim]")
        sys.exit(1)

    print_success("Configuration loaded successfully")

    # Test Sentry connection
    client = create_sentry_client(config)
    if not client:
        sys.exit(1)

    with Progress(
        SpinnerColumn(),
        TextColumn(f"[hawk.gold]{HAWK} Testing Sentry connection...[/hawk.gold]"),
        console=console,
    ) as progress:
        progress.add_task("connect", total=None)

        try:
            projects = client.get_projects(config.sentry.org)
        except SentryAuthenticationError:
            print_error(
                "Authentication failed. Your Sentry token may be invalid or expired.",
                hint="Generate a new token at https://sentry.io/settings/account/api/auth-tokens/",
            )
            sys.exit(1)
        except SentryAPIError as e:
            print_error(f"Connection failed: {e.message}")
            sys.exit(1)

    print_success("Successfully connected to Sentry!")

    # Show connection info
    info_table = Table(show_header=False, border_style="hawk.bronze", box=None)
    info_table.add_column("Label", style="hawk.dim")
    info_table.add_column("Value", style="hawk.feather")

    info_table.add_row("Organization", config.sentry.org)
    info_table.add_row("API URL", config.sentry.base_url)
    info_table.add_row("Projects Available", str(len(projects)))
    info_table.add_row("Configured Projects", ", ".join(config.sentry.projects))

    # Check LLM config
    llm_status = "[green]Configured[/]" if config.llm.api_key else "[yellow]Not set[/]"
    info_table.add_row("LLM Provider", f"{config.llm.provider.value} ({llm_status})")

    # Check Git config
    git_status = "[green]Configured[/]" if config.git.token else "[yellow]Not set[/]"
    info_table.add_row("Git Provider", f"{config.git.provider.value} ({git_status})")

    console.print()
    console.print(Panel(info_table, title=f"{HAWK} Connection Info", border_style="hawk.bronze"))

    # Check if configured projects exist
    available_slugs = {p.get("slug") for p in projects}
    missing = [p for p in config.sentry.projects if p not in available_slugs]

    if missing:
        print_warning(f"Some configured projects not found: {', '.join(missing)}")
        console.print("[hawk.dim]Available projects:[/hawk.dim]")
        for proj in projects[:10]:
            console.print(f"  [hawk.feather]• {proj.get('slug')}[/hawk.feather]")
        if len(projects) > 10:
            console.print(f"  [hawk.dim]... and {len(projects) - 10} more[/hawk.dim]")


@config_group.command("show")
def config_show() -> None:
    """Show current configuration (with sensitive values masked)."""
    print_banner()

    config = get_config_safe()
    if not config:
        sys.exit(1)

    def mask(value: str) -> str:
        if not value:
            return "[hawk.dim](not set)[/hawk.dim]"
        if len(value) <= 8:
            return "[hawk.dim]****[/hawk.dim]"
        return f"{value[:4]}...{value[-4:]}"

    table = Table(
        title=f"{HAWK} Current Configuration",
        title_style="hawk.gold",
        border_style="hawk.bronze",
        show_lines=True,
    )
    table.add_column("Setting", style="hawk.amber")
    table.add_column("Value", style="hawk.feather")

    # Sentry
    table.add_row("[bold]Sentry[/bold]", "")
    table.add_row("  Auth Token", mask(config.sentry.auth_token))
    table.add_row("  Organization", config.sentry.org or "[hawk.dim](not set)[/hawk.dim]")
    table.add_row("  Projects", ", ".join(config.sentry.projects) or "[hawk.dim](none)[/hawk.dim]")
    table.add_row("  Base URL", config.sentry.base_url)

    # Filters
    table.add_row("[bold]Filters[/bold]", "")
    table.add_row("  Min Events", str(config.filters.min_events))
    table.add_row("  Severity Levels", ", ".join(s.value for s in config.filters.severity_levels))
    table.add_row("  Max Age (days)", str(config.filters.max_age_days))

    # LLM
    table.add_row("[bold]LLM[/bold]", "")
    table.add_row("  Provider", config.llm.provider.value)
    table.add_row("  API Key", mask(config.llm.api_key))
    table.add_row("  Model", config.llm.model)

    # Git
    table.add_row("[bold]Git[/bold]", "")
    table.add_row("  Provider", config.git.provider.value)
    table.add_row("  Token", mask(config.git.token))
    table.add_row("  Auto PR", str(config.git.auto_pr))
    table.add_row("  Base Branch", config.git.base_branch)

    # General
    table.add_row("[bold]General[/bold]", "")
    table.add_row("  Debug", str(config.debug))
    table.add_row("  Output Dir", str(config.output_dir))

    console.print()
    console.print(table)


@config_group.command("edit")
def config_edit() -> None:
    """Open configuration file in default editor."""
    import os
    import subprocess

    config_path = Path.cwd() / ".bughawk.yml"

    if not config_path.exists():
        print_error("No configuration file found.")
        console.print("[hawk.dim]Run [hawk.amber]bughawk config init[/hawk.amber] first.[/hawk.dim]")
        sys.exit(1)

    editor = os.environ.get("EDITOR", os.environ.get("VISUAL", "nano"))

    try:
        subprocess.run([editor, str(config_path)], check=True)
        print_success("Configuration file saved")
    except subprocess.CalledProcessError:
        print_error("Editor exited with error")
    except FileNotFoundError:
        print_error(f"Editor not found: {editor}")
        console.print(f"[hawk.dim]Set the EDITOR environment variable or edit {config_path} manually.[/hawk.dim]")


# =============================================================================
# Legacy/Alias Commands
# =============================================================================


@main.command("init")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing configuration")
@click.pass_context
def init_alias(ctx: click.Context, force: bool) -> None:
    """Initialize BugHawk configuration (alias for config init)."""
    ctx.invoke(config_init, force=force)


@main.command("fetch")
@click.pass_context
def fetch_alias(ctx: click.Context) -> None:
    """Fetch issues from Sentry (alias for list-issues)."""
    ctx.invoke(list_issues)


# =============================================================================
# LLM Provider Commands
# =============================================================================


@main.command("providers")
def list_providers() -> None:
    """List all available LLM providers and their default models.

    \b
    Examples:
      bughawk providers              Show all providers
    """
    print_banner()

    from bughawk.fixer.llm_client import get_available_providers, DEFAULT_MODELS
    from bughawk.core.config import LLMProvider

    console.print(f"\n[hawk.gold]{HAWK} Available LLM Providers[/hawk.gold]\n")

    table = Table(show_header=True, header_style="hawk.gold")
    table.add_column("Provider", style="hawk.amber")
    table.add_column("Default Model", style="hawk.feather")
    table.add_column("Requires API Key", style="dim")
    table.add_column("Package", style="dim")

    provider_info = {
        "openai": ("gpt-4", "Yes", "openai"),
        "anthropic": ("claude-sonnet-4-20250514", "Yes", "anthropic"),
        "claude": ("claude-sonnet-4-20250514", "Yes (alias for anthropic)", "anthropic"),
        "azure": ("gpt-4 (via deployment)", "Yes", "openai"),
        "gemini": ("gemini-1.5-pro", "Yes", "google-generativeai"),
        "ollama": ("llama3.1", "No (local)", "requests (included)"),
        "groq": ("llama-3.1-70b-versatile", "Yes", "groq"),
        "mistral": ("mistral-large-latest", "Yes", "mistralai"),
        "cohere": ("command-r-plus", "Yes", "cohere"),
    }

    for provider in get_available_providers():
        info = provider_info.get(provider, ("", "Yes", ""))
        table.add_row(provider, info[0], info[1], info[2])

    console.print(table)

    console.print(f"\n[hawk.dim]To use a provider, set it in your config or use --llm-provider flag:[/hawk.dim]")
    console.print(f"  [hawk.feather]bughawk fix ISSUE_ID --llm-provider claude --llm-model claude-sonnet-4-20250514[/hawk.feather]")
    console.print(f"\n[hawk.dim]Or set environment variables:[/hawk.dim]")
    console.print(f"  [hawk.feather]export BUGHAWK_LLM_PROVIDER=claude[/hawk.feather]")
    console.print(f"  [hawk.feather]export BUGHAWK_LLM_API_KEY=your_api_key[/hawk.feather]")

    console.print(f"\n[hawk.dim]Install provider packages with poetry extras:[/hawk.dim]")
    console.print(f"  [hawk.feather]poetry install --extras default    # OpenAI + Anthropic[/hawk.feather]")
    console.print(f"  [hawk.feather]poetry install --extras all-providers    # All cloud providers[/hawk.feather]")
    console.print(f"  [hawk.feather]poetry install --extras gemini    # Just Gemini[/hawk.feather]")


# =============================================================================
# Helper Functions
# =============================================================================


def _display_fix_proposal(proposal) -> None:
    """Display a fix proposal with formatting."""
    console.print(Panel(
        f"[bold]Fix Proposal[/bold]\n\n"
        f"[hawk.dim]Description:[/] {proposal.fix_description}\n\n"
        f"[hawk.dim]Confidence:[/] {format_confidence(proposal.confidence_score)}\n\n"
        f"[hawk.dim]Explanation:[/]\n{proposal.explanation}\n\n"
        f"[hawk.dim]Files Changed:[/] {len(proposal.code_changes)}",
        title=f"{HAWK} Proposed Fix",
        border_style="green" if proposal.confidence_score >= 0.6 else "yellow",
    ))

    # Show diff preview
    for file_path, diff in proposal.code_changes.items():
        console.print(f"\n[bold hawk.amber]{file_path}[/]")
        # Truncate long diffs
        diff_lines = diff.split("\n")
        if len(diff_lines) > 30:
            display_diff = "\n".join(diff_lines[:30]) + f"\n... ({len(diff_lines) - 30} more lines)"
        else:
            display_diff = diff

        console.print(Syntax(display_diff, "diff", theme="monokai", line_numbers=True))


if __name__ == "__main__":
    main()

# LLM Prompting Guide

This document describes how BugHawk constructs prompts for LLM-powered analysis and fix generation.

## Prompt Structure

BugHawk uses a structured prompt format to get consistent, high-quality responses from LLMs.

### Complete Prompt Template

```markdown
# BugHawk Analysis Request

You are assisting BugHawk, an automated bug hunting and fixing system.
A hawk has spotted prey (a bug) and needs your help analyzing it.

**Issue ID**: {issue_id}
**Occurrences**: {count}
**Severity**: {level}
**Status**: {status}

## Error Summary

**Title**: {title}
**Culprit**: {culprit}
**Exception Type**: {exception_type}
**Exception Message**: {exception_value}
**Language**: {language}
**First Seen**: {first_seen}
**Last Seen**: {last_seen}

## Stack Trace

**{exception_type}**: {exception_value}

```
[APP] File "src/main.py", line 42, in process_data  <-- ERROR
    return data.value
[LIB] File "lib/helper.py", line 10, in helper
    return process_data(item)
```

## Source Code Context

**File**: `src/main.py`
**Error Line**: 42

```python
  40 | def process_data(data):
  41 |     """Process the data object."""
  42 |     return data.value  # <-- ERROR HERE
  43 |
  44 | def main():
```

## Git History

**Last modification to error line:**
- **Author**: Developer <dev@example.com>
- **Date**: 2024-01-15T10:30:00
- **Commit**: `abc123d`
- **Message**: Add data processing

**Recent commits to this file:**
- `abc123d` (2024-01-15) - Add data processing
- `def456e` (2024-01-10) - Initial implementation

## Related Files

### `src/models.py`

```python
   1 | class Data:
   2 |     def __init__(self):
   3 |         self.value = None
```

## Analysis Request

Please analyze this error and provide:

1. **Root Cause Analysis**: What is causing this error?
2. **Impact Assessment**: How severe is this bug? What functionality is affected?
3. **Related Code**: Are there related code paths that might have similar issues?

4. **Proposed Fix**: Provide a code fix with:
   - The specific file(s) to modify
   - The exact changes needed (as a diff if possible)
   - Any test cases that should be added

5. **Confidence Score**: Rate your confidence in the fix from 0.0 to 1.0

---
*Hawk is watching and waiting for your expert analysis.*
```

## Prompt Components

### 1. Header Section

Sets the context and provides metadata about the issue.

```python
def _build_header(self, issue: SentryIssue) -> str:
    return f"""# BugHawk Analysis Request

You are assisting BugHawk, an automated bug hunting and fixing system.
A hawk has spotted prey (a bug) and needs your help analyzing it.

**Issue ID**: {issue.id}
**Occurrences**: {issue.count:,}
**Severity**: {issue.level.value}
**Status**: {issue.status.value}"""
```

### 2. Error Summary

Provides quick overview of the error.

```python
def _build_error_summary(self, issue: SentryIssue, context: EnrichedContext) -> str:
    lines = ["## Error Summary"]
    lines.append(f"\n**Title**: {issue.title}")
    lines.append(f"**Culprit**: {issue.culprit or 'Unknown'}")

    if context.stack_trace:
        lines.append(f"**Exception Type**: {context.stack_trace.exception_type}")
        lines.append(f"**Exception Message**: {context.stack_trace.exception_value}")

    lines.append(f"**Language**: {context.language.title()}")
    # ...
    return "\n".join(lines)
```

### 3. Stack Trace Section

Formats the stack trace for LLM understanding.

```python
def _build_stack_trace_section(self, stack_trace: StackTrace) -> str:
    lines = ["## Stack Trace", ""]
    lines.append(f"**{stack_trace.exception_type}**: {stack_trace.exception_value}")
    lines.append("")
    lines.append("```")

    for i, frame in enumerate(reversed(stack_trace.frames)):
        marker = " <-- ERROR" if i == 0 and frame.in_app else ""
        app_marker = "[APP]" if frame.in_app else "[LIB]"

        lines.append(
            f'{app_marker} File "{frame.filename}", line {frame.line_number}, '
            f'in {frame.function}{marker}'
        )

        if frame.context_line:
            lines.append(f"    {frame.context_line.strip()}")

    lines.append("```")
    return "\n".join(lines)
```

### 4. Code Context Section

Shows the source code around the error.

```python
def _build_code_section(self, context: EnrichedContext) -> str:
    lines = ["## Source Code Context", ""]
    lines.append(f"**File**: `{context.code_context.file_path}`")

    if context.code_context.error_line:
        lines.append(f"**Error Line**: {context.code_context.error_line}")

    lines.append("")
    lines.append(f"```{context.language}")

    for line_num, content in sorted(context.code_context.surrounding_lines.items()):
        error_marker = ""
        if line_num == context.code_context.error_line:
            error_marker = "  # <-- ERROR HERE"

        lines.append(f"{line_num:4d} | {content}{error_marker}")

    lines.append("```")
    return "\n".join(lines)
```

### 5. Git History Section

Provides context about recent changes.

```python
def _build_git_section(self, context: EnrichedContext) -> str:
    lines = ["## Git History"]

    if context.blame_info:
        error_blame = find_blame_for_error_line(context)
        if error_blame:
            lines.append("")
            lines.append("**Last modification to error line:**")
            lines.append(f"- **Author**: {error_blame.author}")
            lines.append(f"- **Commit**: `{error_blame.commit_hash[:7]}`")
            lines.append(f"- **Message**: {error_blame.commit_message}")

    if context.recent_commits:
        lines.append("")
        lines.append("**Recent commits to this file:**")
        for commit in context.recent_commits[:5]:
            lines.append(f"- `{commit.short_hash}` - {commit.message[:60]}")

    return "\n".join(lines)
```

### 6. Analysis Request Section

Tells the LLM what we need.

```python
def _build_analysis_request(self, include_fix_request: bool) -> str:
    lines = ["## Analysis Request", ""]
    lines.append("Please analyze this error and provide:")
    lines.append("")
    lines.append("1. **Root Cause Analysis**: What is causing this error?")
    lines.append("2. **Impact Assessment**: How severe is this bug?")
    lines.append("3. **Related Code**: Are there similar issues elsewhere?")

    if include_fix_request:
        lines.append("")
        lines.append("4. **Proposed Fix**: Provide a code fix with:")
        lines.append("   - The specific file(s) to modify")
        lines.append("   - The exact changes needed (as a diff)")
        lines.append("   - Any test cases to add")
        lines.append("")
        lines.append("5. **Confidence Score**: Rate your confidence (0.0 to 1.0)")

    return "\n".join(lines)
```

## Response Parsing

### Expected Response Format

BugHawk expects LLM responses in this format:

```markdown
## Root Cause Analysis

The error occurs because `data` is None when `process_data()` is called.
This happens when...

## Impact Assessment

**Severity**: High
**Affected Functionality**: Data processing pipeline
**User Impact**: Users cannot process data when input is missing

## Related Code

Similar issues may exist in:
- `src/handlers/user_handler.py:45` - Same pattern used
- `src/services/data_service.py:78` - Similar null check missing

## Proposed Fix

### File: `src/main.py`

```diff
@@ -40,3 +40,5 @@
 def process_data(data):
     """Process the data object."""
+    if data is None:
+        return None
     return data.value
```

### Test Case

```python
def test_process_data_with_none():
    assert process_data(None) is None
```

## Confidence Score: 0.85

High confidence because:
- Clear null reference pattern
- Simple fix with minimal side effects
- Common pattern in the codebase
```

### Parsing Logic

```python
def parse_llm_response(response: str) -> FixProposal:
    """Parse LLM response into FixProposal."""

    # Extract confidence score
    confidence_match = re.search(
        r"Confidence.*?(\d+\.?\d*)",
        response,
        re.IGNORECASE
    )
    confidence = float(confidence_match.group(1)) if confidence_match else 0.5

    # Extract diff blocks
    diff_pattern = r"```diff\n(.*?)```"
    diffs = re.findall(diff_pattern, response, re.DOTALL)

    # Extract file paths
    file_pattern = r"File:\s*`?([^\n`]+)`?"
    files = re.findall(file_pattern, response)

    # Build code changes dict
    code_changes = {}
    for file, diff in zip(files, diffs):
        code_changes[file.strip()] = diff.strip()

    # Extract description
    fix_desc = extract_section(response, "Proposed Fix")

    # Extract explanation
    explanation = extract_section(response, "Root Cause Analysis")

    return FixProposal(
        issue_id=current_issue_id,
        fix_description=fix_desc,
        code_changes=code_changes,
        confidence_score=confidence,
        explanation=explanation,
    )
```

## LLM Configuration

### Provider-Specific Settings

```yaml
# OpenAI
llm:
  provider: openai
  model: gpt-4
  max_tokens: 4096
  temperature: 0.1

# Anthropic
llm:
  provider: anthropic
  model: claude-3-opus-20240229
  max_tokens: 4096
  temperature: 0.1

# Azure OpenAI
llm:
  provider: azure
  model: gpt-4
  api_base: https://your-resource.openai.azure.com
  api_version: "2024-02-15-preview"
```

### Token Management

BugHawk manages token limits by:

1. **Truncating long files**: Only include relevant portions
2. **Limiting related files**: Include max 3 related files
3. **Summarizing git history**: Show max 5 recent commits
4. **Progressive disclosure**: Add more context if needed

### Temperature Settings

- **Analysis (0.1)**: Low temperature for consistent analysis
- **Fix generation (0.2)**: Slightly higher for creative solutions
- **Explanation (0.3)**: Higher for natural language

## Best Practices

### 1. Provide Rich Context

More context leads to better fixes:
- Include surrounding code (50+ lines)
- Add related files when relevant
- Include git history for context

### 2. Be Explicit About Output Format

The prompt clearly specifies:
- Expected sections
- Diff format for code changes
- Confidence score format

### 3. Include Guardrails

The prompt asks for:
- Confidence scoring
- Impact assessment
- Related code identification

### 4. Validate Responses

Always validate LLM responses:
- Check syntax validity
- Verify file paths exist
- Ensure diff can be applied

## Troubleshooting

### Low-Quality Responses

If getting poor responses:
1. Add more code context
2. Include more stack trace frames
3. Add example of expected output format

### Parsing Failures

If parsing fails:
1. Check response format
2. Add fallback parsing logic
3. Log raw response for debugging

### High Token Usage

If using too many tokens:
1. Reduce context lines
2. Limit related files
3. Truncate long file contents

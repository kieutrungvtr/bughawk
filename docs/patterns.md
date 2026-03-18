# Error Pattern Reference

BugHawk uses pattern matching to quickly identify and suggest fixes for common error types. This document describes the built-in patterns and how to extend them.

## Pattern Categories

### 1. Null Reference Errors (`NULL_REFERENCE`)

Errors caused by accessing properties or methods on null/undefined values.

**Exception Types:**
- `TypeError` (JavaScript/TypeScript)
- `NullPointerException` (Java)
- `AttributeError` (Python)
- `NullReferenceException` (C#)

**Message Patterns:**
```
Cannot read property '.*' of (undefined|null)
'NoneType' object has no attribute
null pointer
Object reference not set
```

**Common Causes:**
- Accessing property on undefined/null variable
- Missing null check before method call
- Async data not loaded yet
- Optional parameter not provided

**Typical Fixes:**
```python
# Before
result = user.name

# After (Python)
result = user.name if user else None

# After (JavaScript)
result = user?.name

# After (with default)
result = (user || {}).name || 'Unknown'
```

---

### 2. Key/Index Errors (`KEY_ERROR`)

Errors from accessing non-existent dictionary keys or array indices.

**Exception Types:**
- `KeyError` (Python)
- `IndexError` (Python)
- `TypeError: Cannot read property` (JavaScript)
- `ArrayIndexOutOfBoundsException` (Java)

**Message Patterns:**
```
KeyError: '.*'
list index out of range
index .* is out of bounds
```

**Common Causes:**
- Accessing non-existent dictionary key
- Array index exceeds length
- Typo in key name
- Missing data validation

**Typical Fixes:**
```python
# Before
value = data['key']

# After (Python - with default)
value = data.get('key', default_value)

# After (Python - with check)
if 'key' in data:
    value = data['key']

# After (JavaScript)
value = data['key'] ?? defaultValue
```

---

### 3. Type Errors (`TYPE_ERROR`)

Errors from incompatible types in operations.

**Exception Types:**
- `TypeError` (Python/JavaScript)
- `ClassCastException` (Java)
- `InvalidCastException` (C#)

**Message Patterns:**
```
cannot concatenate .* and .*
unsupported operand type
Expected .* but got
is not a function
```

**Common Causes:**
- String/number concatenation without conversion
- Calling method on wrong type
- Incorrect function arguments
- Missing type conversion

**Typical Fixes:**
```python
# Before (Python)
result = "Count: " + count

# After
result = "Count: " + str(count)
result = f"Count: {count}"
```

---

### 4. Import/Module Errors (`IMPORT_ERROR`)

Errors from failed module imports.

**Exception Types:**
- `ImportError` (Python)
- `ModuleNotFoundError` (Python)
- `Cannot find module` (JavaScript)

**Message Patterns:**
```
No module named '.*'
Cannot find module
Module not found
```

**Common Causes:**
- Missing dependency
- Typo in module name
- Circular import
- Missing __init__.py
- Wrong Python environment

**Typical Fixes:**
- Install missing package
- Fix import path
- Resolve circular dependencies
- Check virtual environment

---

### 5. Async/Await Errors (`ASYNC_ERROR`)

Errors in asynchronous code.

**Exception Types:**
- `UnhandledPromiseRejectionWarning` (Node.js)
- `RuntimeError: cannot reuse` (Python asyncio)
- Various timeout errors

**Message Patterns:**
```
await is only valid in async function
Promise.*rejected
coroutine.*never awaited
```

**Common Causes:**
- Missing await keyword
- Calling async function without await
- Race conditions
- Unhandled promise rejections

**Typical Fixes:**
```javascript
// Before
const result = fetchData();

// After
const result = await fetchData();
```

---

### 6. Syntax Errors (`SYNTAX_ERROR`)

Code parsing failures.

**Exception Types:**
- `SyntaxError` (Python/JavaScript)
- Various parse errors

**Message Patterns:**
```
SyntaxError: .*
unexpected token
invalid syntax
```

**Common Causes:**
- Missing brackets/parentheses
- Incorrect indentation
- Missing colons
- Unclosed strings

**Typical Fixes:**
- Add missing syntax elements
- Fix indentation
- Close strings/brackets

---

### 7. Value Errors (`VALUE_ERROR`)

Errors from invalid values.

**Exception Types:**
- `ValueError` (Python)
- `IllegalArgumentException` (Java)
- `ArgumentError` (Ruby)

**Message Patterns:**
```
ValueError: .*
invalid literal for int
invalid value
```

**Common Causes:**
- Invalid conversion (e.g., `int("abc")`)
- Out of range values
- Invalid enum values
- Missing required fields

**Typical Fixes:**
```python
# Before
number = int(user_input)

# After
try:
    number = int(user_input)
except ValueError:
    number = 0  # default
```

---

### 8. Connection/Network Errors (`CONNECTION_ERROR`)

Network-related failures.

**Exception Types:**
- `ConnectionError` (Python)
- `TimeoutError`
- `SocketException` (Java)
- `ECONNREFUSED` (Node.js)

**Message Patterns:**
```
Connection refused
Connection timed out
Network is unreachable
```

**Common Causes:**
- Service unavailable
- Firewall blocking
- DNS resolution failure
- Invalid URL/port

**Typical Fixes:**
- Add retry logic
- Add timeout handling
- Implement circuit breaker
- Add fallback behavior

---

### 9. Permission Errors (`PERMISSION_ERROR`)

File/resource access denials.

**Exception Types:**
- `PermissionError` (Python)
- `AccessDeniedException` (Java)
- `EACCES` (Node.js)

**Message Patterns:**
```
Permission denied
Access is denied
EACCES
```

**Common Causes:**
- Insufficient file permissions
- Wrong user/group
- Missing directory
- Locked file

**Typical Fixes:**
- Check/change file permissions
- Run with appropriate privileges
- Create directories if needed
- Handle locked files gracefully

---

## Adding Custom Patterns

### Pattern Structure

```python
from bughawk.analyzer.pattern_matcher import ErrorPattern, ErrorCategory

pattern = ErrorPattern(
    id="unique-id",
    name="Human Readable Name",
    category=ErrorCategory.NULL_REFERENCE,
    languages=["python", "javascript"],
    exception_types=["TypeError", "AttributeError"],
    message_patterns=[
        r"specific.*regex.*pattern",
        r"another pattern",
    ],
    common_causes=[
        "Cause 1",
        "Cause 2",
    ],
    typical_fixes=[
        "Fix approach 1",
        "Fix approach 2",
    ],
)
```

### Fix Templates

Fix templates use placeholders for dynamic content:

```python
from bughawk.analyzer.pattern_matcher import FixTemplate

template = FixTemplate(
    pattern_id="null-check",
    description="Add null/undefined check",
    code_template="""
if ({variable} is not None):
    {original_code}
""",
    languages=["python"],
    explanation="Adds a null check to prevent AttributeError",
    caveats=[
        "May hide underlying data issues",
        "Consider why the value is None",
    ],
)
```

### Registering Patterns

```python
from bughawk.analyzer.pattern_matcher import PatternMatcher

matcher = PatternMatcher()
matcher.register_pattern(custom_pattern)
matcher.register_fix_template(custom_template)
```

## Pattern Matching Algorithm

1. **Exception Type Match**: Check if exception type matches pattern
2. **Message Pattern Match**: Regex match against error message
3. **Code Context Match**: Check code for pattern indicators
4. **Language Match**: Ensure pattern applies to detected language

### Confidence Scoring

```python
confidence = 0.0

# Exception type match: +0.4
if exception_type in pattern.exception_types:
    confidence += 0.4

# Message pattern match: +0.4
if any(re.search(p, message) for p in pattern.message_patterns):
    confidence += 0.4

# Code context indicators: +0.2
if has_code_indicators:
    confidence += 0.2

# Threshold for confident match: 0.7
```

## Best Practices

### Writing Good Patterns

1. **Be specific**: Avoid overly broad regex patterns
2. **Test thoroughly**: Verify with real error examples
3. **Document causes**: Help users understand the root cause
4. **Provide actionable fixes**: Give clear fix directions

### Pattern Maintenance

1. Keep patterns updated with new framework versions
2. Add patterns for recurring errors in your codebase
3. Remove deprecated patterns
4. Track pattern match success rates

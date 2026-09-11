import re


def parse_env(text: str) -> dict[str, str]:
    """Parse a .env-style configuration format.
    
    Args:
        text: Configuration text with lines separated by \n
        
    Returns:
        Dictionary mapping keys to values, with last occurrence winning
        and order following first appearance of each key
        
    Raises:
        ValueError: If a line is malformed (no =, invalid key, etc)
    """
    result = {}
    key_order = []  # Track first appearance order
    
    lines = text.split('\n')
    
    for line_num, line in enumerate(lines, 1):
        # Strip trailing \r if present
        if line.endswith('\r'):
            line = line[:-1]
        
        original_line = line  # Store for error messages
        
        # Skip empty or whitespace-only lines
        if not line.strip():
            continue
        
        # Skip comment lines
        if line.lstrip()[0] == '#':
            continue
        
        # Must contain at least one =
        if '=' not in line:
            raise ValueError(f"invalid line {line_num}: {original_line}")
        
        # Split on first = only
        key_raw, value_raw = line.split('=', 1)
        
        # Process key: strip whitespace, handle export prefix
        key = key_raw.strip()
        if key.startswith('export '):
            key = key[7:].strip()
        
        # Validate key
        if not key or not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', key):
            raise ValueError(f"invalid line {line_num}: {original_line}")
        
        # Process value
        value = _parse_value(value_raw)
        
        # Track key order (only on first appearance)
        if key not in result:
            key_order.append(key)
        
        # Last occurrence wins
        result[key] = value
    
    # Rebuild dict with first-appearance order
    ordered_result = {}
    for key in key_order:
        ordered_result[key] = result[key]
    
    return ordered_result


def _parse_value(value_raw: str) -> str:
    """Parse the value part of an assignment.
    
    Handles:
    - Double-quoted strings with escape sequences
    - Single-quoted strings (literal, no escapes)
    - Unquoted values with trailing comments
    """
    value = value_raw.strip()
    
    # Double-quoted string
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        # Remove surrounding quotes
        content = value[1:-1]
        # Expand escape sequences
        content = _expand_escapes(content)
        return content
    
    # Single-quoted string
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        # Remove surrounding quotes, take literally
        return value[1:-1]
    
    # Unquoted value with potential trailing comment
    # A trailing comment is # preceded by at least one whitespace
    # Find the last occurrence of whitespace followed by #
    for i in range(len(value) - 1, 0, -1):
        if value[i] == '#' and value[i - 1].isspace():
            # Found trailing comment
            value = value[:i].strip()
            break
    
    return value


def _expand_escapes(content: str) -> str:
    r"""Expand escape sequences in double-quoted strings.
    
    Handles: \n, \t, \r, \", \\
    Other \x sequences are left as-is.
    """
    result = []
    i = 0
    while i < len(content):
        if content[i] == '\\' and i + 1 < len(content):
            next_char = content[i + 1]
            if next_char == 'n':
                result.append('\n')
                i += 2
            elif next_char == 't':
                result.append('\t')
                i += 2
            elif next_char == 'r':
                result.append('\r')
                i += 2
            elif next_char == '"':
                result.append('"')
                i += 2
            elif next_char == '\\':
                result.append('\\')
                i += 2
            else:
                # Not a recognized escape, leave as-is
                result.append(content[i])
                result.append(next_char)
                i += 2
        else:
            result.append(content[i])
            i += 1
    return ''.join(result)

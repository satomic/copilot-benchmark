def to_roman(n: int) -> str:
    """Convert an integer to its Roman numeral representation.
    
    Args:
        n: An integer in the range 1..3999
        
    Returns:
        The standard (subtractive) Roman numeral as an uppercase string.
        
    Raises:
        TypeError: If n is not an int, or is a bool
        ValueError: If n is outside the range 1..3999
    """
    # Reject bool explicitly (bool is a subclass of int)
    if isinstance(n, bool):
        raise TypeError(f"expected an integer, not {type(n).__name__}")
    
    # Check type
    if not isinstance(n, int):
        raise TypeError(f"expected an integer, not {type(n).__name__}")
    
    # Check range
    if n < 1 or n > 3999:
        raise ValueError(f"integer must be in range 1..3999, not {n}")
    
    # Mapping of values to Roman numerals in descending order
    # Includes standard subtractive pairs
    _values_to_numerals = [
        (1000, 'M'),
        (900, 'CM'),
        (500, 'D'),
        (400, 'CD'),
        (100, 'C'),
        (90, 'XC'),
        (50, 'L'),
        (40, 'XL'),
        (10, 'X'),
        (9, 'IX'),
        (5, 'V'),
        (4, 'IV'),
        (1, 'I'),
    ]
    
    result = ''
    for value, numeral in _values_to_numerals:
        count = n // value
        if count:
            result += numeral * count
            n -= value * count
    
    return result

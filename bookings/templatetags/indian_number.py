from django import template

register = template.Library()

@register.filter
def indian_number(value):
    """
    Format a number with Indian style commas (e.g., 12,34,56,789)
    without decimal places
    """
    try:
        # Convert to integer to remove decimal part
        num = int(round(float(value)))
    except (ValueError, TypeError):
        return value
    
    s = str(num)
    n = len(s)
    
    # Handle numbers with <= 3 digits
    if n <= 3:
        return s
    
    # Start grouping from the right
    result = []
    # Process last 3 digits
    result.append(s[-3:])
    
    # Process remaining digits in groups of 2
    remaining = s[:-3]
    while remaining:
        if len(remaining) <= 2:
            result.append(remaining)
            break
        result.append(remaining[-2:])
        remaining = remaining[:-2]
    
    return ','.join(reversed(result))

from datetime import timedelta
from typing import Optional, Union


def format_duration(td: Union[timedelta, float, int], compact: bool = False) -> str:
    """
    Converts a timedelta object or seconds into a human-readable duration string.

    Args:
        td: A timedelta object, or number of seconds as float/int.
        compact: If True, returns a shorter format (e.g. "1h 2m" instead of "1h 2m 0s")

    Returns:
        Formatted duration string

    Examples:
        >>> format_duration(timedelta(seconds=3725))
        '1h 2m 5s'
        >>> format_duration(3725, compact=True)
        '1h 2m'
    """
    # Convert to timedelta if needed
    if isinstance(td, (int, float)):
        td = timedelta(seconds=td)

    total_seconds = int(td.total_seconds())

    # Handle the case of very large times
    if total_seconds < 0:
        return "0s"

    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    parts = []

    # Only include days if they exist
    if days > 0:
        parts.append(f"{days}d")

    # For hours, minutes, and seconds, we apply the compact logic
    if hours > 0:
        parts.append(f"{hours}h")

    if minutes > 0 or (hours > 0 and seconds > 0 and not compact):
        parts.append(f"{minutes}m")

    # In compact mode, skip seconds if we have larger units
    if seconds > 0 or (not compact and not parts):
        parts.append(f"{seconds}s")

    # Special case: handle "0s" for empty result
    if not parts:
        return "0s"

    return " ".join(parts)


def format_sec(secs: float) -> str:
    if secs == 0:
        return "None"
    elif secs < 1e-3:
        return f"{secs * 1e6:.3f}".rstrip("0").rstrip(".") + " µs"
    elif secs < 1:
        return f"{secs * 1e3:.3f}".rstrip("0").rstrip(".") + " ms"
    return f"{secs:.3f}".rstrip("0").rstrip(".") + "s"


def human_readable_bytes(
    num: Union[int, float],
    suffix: str = "B",
    precision: int = 1,
    decimal_places: Optional[int] = None,
    binary: bool = True,
) -> str:
    """
    Converts bytes to a human-readable string format.

    Args:
        num: Number of bytes
        suffix: Unit suffix to append (default: "B")
        precision: Number of decimal places (default: 1)
        decimal_places: If provided, overrides precision to use exactly this many decimal places
        binary: If True, use 1024 as base (KiB, MiB), otherwise use 1000 (KB, MB)

    Returns:
        Formatted byte string

    Examples:
        >>> human_readable_bytes(1500)
        '1.5KB'
        >>> human_readable_bytes(1500, binary=False)
        '1.5KB'
        >>> human_readable_bytes(1048576, decimal_places=2)
        '1.00MB'
    """
    # Safety check for non-numeric inputs
    try:
        num_float = float(num)
    except (ValueError, TypeError):
        return "0B"

    if num_float == 0:
        return f"0{suffix}"

    # Use 1024 for binary (KiB, MiB) or 1000 for decimal (KB, MB)
    base = 1024 if binary else 1000

    # Determine appropriate unit
    units = ["", "K", "M", "G", "T", "P", "E", "Z", "Y"]
    exponent = 0

    # Simpler approach for determining exponent
    value = abs(num_float)
    while value >= base and exponent < len(units) - 1:
        value /= base
        exponent += 1

    # Calculate the final display value
    display_value = num_float / (base**exponent)

    # Use specified decimal places or the default precision
    if decimal_places is not None:
        return f"{display_value:.{decimal_places}f}{units[exponent]}{suffix}"
    else:
        return (
            f"{round(display_value, precision):.{precision}f}{units[exponent]}{suffix}"
        )


def calculate_transfer_stats(current: int, total: int, elapsed_time: float):
    """
    Calculate transfer statistics like speed and ETA.

    Args:
        current: Bytes transferred so far
        total: Total bytes to transfer
        elapsed_time: Time elapsed in seconds

    Returns:
        Tuple of (speed_bytes_per_sec, eta_seconds)
    """
    if elapsed_time <= 0 or current <= 0:
        return 0, 0

    speed = current / elapsed_time

    if speed <= 0 or current >= total:
        eta_seconds = 0
    else:
        eta_seconds = (total - current) / speed

    return speed, eta_seconds

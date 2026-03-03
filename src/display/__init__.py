"""E-Ink display drivers."""

from .base import EinkDisplay


def get_display(model: str) -> EinkDisplay:
    """Return the display driver for the given model name.

    Args:
        model: One of '7in3e' or '13in3e'.

    Raises:
        ValueError: If model is not recognized.
    """
    if model == "7in3e":
        from .epd7in3e import Display7in3e
        return Display7in3e()
    elif model == "13in3e":
        from .epd13in3e import Display13in3e
        return Display13in3e()
    else:
        raise ValueError(f"Unknown display model: {model!r}. Choose '7in3e' or '13in3e'.")

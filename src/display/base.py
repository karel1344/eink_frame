"""Abstract base class for E-Ink displays."""

from __future__ import annotations

from abc import ABC, abstractmethod

from PIL import Image


class EinkDisplay(ABC):
    """Unified interface for all supported E-Ink display models.

    Usage::

        display = get_display("7in3e")
        display.init()
        display.show(image)   # PIL Image, any size/mode
        display.sleep()
    """

    @property
    @abstractmethod
    def width(self) -> int:
        """Display width in pixels."""

    @property
    @abstractmethod
    def height(self) -> int:
        """Display height in pixels."""

    @property
    @abstractmethod
    def color_mode(self) -> str:
        """'6color' or '4gray'"""

    @abstractmethod
    def init(self) -> None:
        """Initialize hardware (SPI, GPIO). Must be called before display/clear."""

    @abstractmethod
    def show(self, image: Image.Image) -> None:
        """Display a PIL Image. Image must already be resized to (width, height)."""

    @abstractmethod
    def clear(self) -> None:
        """Fill display with white."""

    @abstractmethod
    def sleep(self) -> None:
        """Put display into low-power sleep mode."""

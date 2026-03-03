"""Wrapper for Waveshare 13.3" Spectra 6 E-Ink display (epd13in3e)."""

from __future__ import annotations

import logging

from PIL import Image

from ..base import EinkDisplay

logger = logging.getLogger(__name__)

# Driver native orientation: portrait (1200 wide × 1600 tall).
# For landscape mounting set rotation=90 in config — image_processor will
# produce a 1600×1200 canvas and getbuffer() auto-rotates it to 1200×1600.
_WIDTH  = 1200
_HEIGHT = 1600


class Display13in3e(EinkDisplay):
    """Waveshare 13.3" Spectra 6-color display (1200×1600 native / 1600×1200 landscape).

    Colors: Black, White, Yellow, Red, Blue, Green.
    Dual CS architecture: CS_M drives the left half, CS_S the right half.

    Hardware is initialized lazily — importing this module is safe on Mac.
    init() must be called before show()/clear().
    """

    def __init__(self) -> None:
        self._epd = None

    @property
    def width(self) -> int:
        return _WIDTH

    @property
    def height(self) -> int:
        return _HEIGHT

    @property
    def color_mode(self) -> str:
        return "6color"

    def init(self) -> None:
        from .driver import EPD
        self._epd = EPD()
        if self._epd.init() != 0:
            raise RuntimeError("Display init failed")
        logger.info("Display 13in3e initialized (%dx%d, 6-color)", _WIDTH, _HEIGHT)

    def show(self, image: Image.Image) -> None:
        if self._epd is None:
            raise RuntimeError("Call init() before show()")
        buf = self._epd.getbuffer(image)
        self._epd.display(buf)
        logger.debug("Display updated")

    def clear(self) -> None:
        if self._epd is None:
            raise RuntimeError("Call init() before clear()")
        self._epd.Clear()
        logger.debug("Display cleared")

    def sleep(self) -> None:
        if self._epd is None:
            return
        self._epd.sleep()
        self._epd = None
        logger.info("Display sleeping")

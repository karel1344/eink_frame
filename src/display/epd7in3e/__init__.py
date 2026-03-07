"""Wrapper for Waveshare 7.3" 6-color E-Ink display (epd7in3e)."""

from __future__ import annotations

import logging

from PIL import Image

from ..base import EinkDisplay

logger = logging.getLogger(__name__)

_WIDTH = 800
_HEIGHT = 480


class Display7in3e(EinkDisplay):
    """Waveshare 7.3" Spectra 6-color display (800×480).

    Colors: Black, White, Yellow, Red, Blue, Green.
    The Waveshare driver handles 6-color quantization internally via getbuffer().

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
        logger.info("Display 7in3e initialized (%dx%d, 6-color)", _WIDTH, _HEIGHT)

    def show(self, image: Image.Image) -> None:
        if self._epd is None:
            raise RuntimeError("Call init() before show()")
        buf = self._epd.getbuffer(image)
        self._epd.display(buf)
        logger.debug("Display updated")

    def show_fast(self, image: Image.Image) -> None:
        """Quick refresh — 이전 이미지의 잔상이 남을 수 있음 (실험적).

        0x12 커맨드에 0x01 파라미터를 전달해 패널의 fast-refresh를 시도.
        패널이 지원하지 않으면 일반 리프레시와 동일하게 동작한다.
        """
        if self._epd is None:
            raise RuntimeError("Call init() before show_fast()")
        buf = self._epd.getbuffer(image)
        self._epd.display_fast(buf)
        logger.debug("Display fast-updated")

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

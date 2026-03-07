# *****************************************************************************
# * | File        :   epd13in3e.py
# * | Function    :   Waveshare 13.3" Spectra 6 E-Ink display driver
# * | Info        :   1200x1600, 6-color (Black/White/Yellow/Red/Blue/Green)
# * |                 Dual CS (CS_M = left half, CS_S = right half)
# * |                 Based on Waveshare epd12in48 demo code
# *****************************************************************************

import logging

from . import config as epdconfig
from PIL import Image

# Display resolution (portrait orientation in driver; width=1200, height=1600)
EPD_WIDTH  = 1200
EPD_HEIGHT = 1600

logger = logging.getLogger(__name__)


class EPD:
    def __init__(self):
        self.width  = EPD_WIDTH
        self.height = EPD_HEIGHT

        self.BLACK  = 0x000000
        self.WHITE  = 0xffffff
        self.YELLOW = 0x00ffff
        self.RED    = 0x0000ff
        self.BLUE   = 0xff0000
        self.GREEN  = 0x00ff00

        self.EPD_CS_M_PIN = epdconfig.EPD_CS_M_PIN
        self.EPD_CS_S_PIN = epdconfig.EPD_CS_S_PIN
        self.EPD_DC_PIN   = epdconfig.EPD_DC_PIN
        self.EPD_RST_PIN  = epdconfig.EPD_RST_PIN
        self.EPD_BUSY_PIN = epdconfig.EPD_BUSY_PIN
        self.EPD_PWR_PIN  = epdconfig.EPD_PWR_PIN

    # -------------------------------------------------------------------------
    # Low-level helpers
    # -------------------------------------------------------------------------

    def Reset(self):
        for _ in range(5):
            epdconfig.digital_write(self.EPD_RST_PIN, 1)
            epdconfig.delay_ms(30)
            epdconfig.digital_write(self.EPD_RST_PIN, 0)
            epdconfig.delay_ms(30)
        epdconfig.digital_write(self.EPD_RST_PIN, 1)
        epdconfig.delay_ms(30)

    def CS_ALL(self, value):
        epdconfig.digital_write(self.EPD_CS_M_PIN, value)
        epdconfig.digital_write(self.EPD_CS_S_PIN, value)

    def SendCommand(self, command):
        epdconfig.digital_write(self.EPD_DC_PIN, 0)   # DC=0: command
        epdconfig.spi_writebyte(command)

    def SendData(self, data):
        epdconfig.digital_write(self.EPD_DC_PIN, 1)   # DC=1: data
        epdconfig.spi_writebyte(data)

    def SendData2(self, buf):
        epdconfig.digital_write(self.EPD_DC_PIN, 1)
        epdconfig.spi_writebyte2(buf, len(buf))

    def ReadBusyH(self):
        logger.debug("e-Paper busy")
        while epdconfig.digital_read(self.EPD_BUSY_PIN) == 0:   # 0=busy, 1=idle
            epdconfig.delay_ms(5)
        logger.debug("e-Paper busy release")

    def TurnOnDisplay(self):
        self.CS_ALL(0)
        self.SendCommand(0x04)   # PON
        self.CS_ALL(1)
        self.ReadBusyH()
        epdconfig.delay_ms(50)

        self.CS_ALL(0)
        self.SendCommand(0x12)   # DRF
        self.SendData(0x00)
        self.CS_ALL(1)
        self.ReadBusyH()

        self.CS_ALL(0)
        self.SendCommand(0x02)   # POF
        self.SendData(0x00)
        self.CS_ALL(1)
        logger.debug("TurnOnDisplay done")

    # -------------------------------------------------------------------------
    # Initialisation
    # -------------------------------------------------------------------------

    def init(self) -> int:
        epdconfig.module_init()

        self.Reset()
        self.ReadBusyH()

        # ANTM — CS_M only
        epdconfig.digital_write(self.EPD_CS_M_PIN, 0)
        self.SendCommand(0x74)
        for b in [0xC0, 0x1C, 0x1C, 0xCC, 0xCC, 0xCC, 0x15, 0x15, 0x55]:
            self.SendData(b)
        self.CS_ALL(1)

        # CMD66 — both CS
        self.CS_ALL(0)
        self.SendCommand(0xF0)
        for b in [0x49, 0x55, 0x13, 0x5D, 0x05, 0x10]:
            self.SendData(b)
        self.CS_ALL(1)

        # PSR — both CS
        self.CS_ALL(0)
        self.SendCommand(0x00)
        self.SendData(0xDF)
        self.SendData(0x69)
        self.CS_ALL(1)

        # CDI — both CS
        self.CS_ALL(0)
        self.SendCommand(0x50)
        self.SendData(0xF7)
        self.CS_ALL(1)

        # TCON — both CS
        self.CS_ALL(0)
        self.SendCommand(0x60)
        self.SendData(0x03)
        self.SendData(0x03)
        self.CS_ALL(1)

        # AGID — both CS
        self.CS_ALL(0)
        self.SendCommand(0x86)
        self.SendData(0x10)
        self.CS_ALL(1)

        # PWS — both CS
        self.CS_ALL(0)
        self.SendCommand(0xE3)
        self.SendData(0x22)
        self.CS_ALL(1)

        # CCSET — both CS
        self.CS_ALL(0)
        self.SendCommand(0xE0)
        self.SendData(0x01)
        self.CS_ALL(1)

        # TRES (resolution) — both CS: 0x04B0=1200, 0x0320=800
        self.CS_ALL(0)
        self.SendCommand(0x61)
        for b in [0x04, 0xB0, 0x03, 0x20]:
            self.SendData(b)
        self.CS_ALL(1)

        # PWR — CS_M only
        epdconfig.digital_write(self.EPD_CS_M_PIN, 0)
        self.SendCommand(0x01)
        for b in [0x0F, 0x00, 0x28, 0x2C, 0x28, 0x38]:
            self.SendData(b)
        self.CS_ALL(1)

        # EN_BUF — CS_M only
        epdconfig.digital_write(self.EPD_CS_M_PIN, 0)
        self.SendCommand(0xB6)
        self.SendData(0x07)
        self.CS_ALL(1)

        # BTST_P — CS_M only
        epdconfig.digital_write(self.EPD_CS_M_PIN, 0)
        self.SendCommand(0x06)
        self.SendData(0xE8)
        self.SendData(0x28)
        self.CS_ALL(1)

        # BOOST_VDDP_EN — CS_M only
        epdconfig.digital_write(self.EPD_CS_M_PIN, 0)
        self.SendCommand(0xB7)
        self.SendData(0x01)
        self.CS_ALL(1)

        # BTST_N — CS_M only
        epdconfig.digital_write(self.EPD_CS_M_PIN, 0)
        self.SendCommand(0x05)
        self.SendData(0xE8)
        self.SendData(0x28)
        self.CS_ALL(1)

        # BUCK_BOOST_VDDN — CS_M only
        epdconfig.digital_write(self.EPD_CS_M_PIN, 0)
        self.SendCommand(0xB0)
        self.SendData(0x01)
        self.CS_ALL(1)

        # TFT_VCOM_POWER — CS_M only
        epdconfig.digital_write(self.EPD_CS_M_PIN, 0)
        self.SendCommand(0xB1)
        self.SendData(0x02)
        self.CS_ALL(1)

        logger.info("EPD 13in3e initialized (%dx%d, 6-color)", self.width, self.height)
        return 0

    # -------------------------------------------------------------------------
    # Image conversion
    # -------------------------------------------------------------------------

    def getbuffer(self, image: Image.Image) -> list:
        """Quantize PIL image to 6-color palette and pack 2 pixels per byte."""
        # Calibrated palette: measured actual display colors instead of ideal
        # fully-saturated values.  Using real colors improves dithering because
        # Floyd-Steinberg error diffusion is computed against what the panel
        # actually reproduces, not what we wish it would.
        # Index order must match panel color codes: 0=Black 1=White 2=Yellow
        # 3=Red 4=unused(→Black) 5=Blue 6=Green.
        pal_image = Image.new("P", (1, 1))
        # Hybrid palette: ideal Black/White to preserve grayscale tonal range
        # (midpoint stays at 128, grays dither correctly), calibrated values for
        # the four chromatic inks where the display deviates most from ideal.
        pal_image.putpalette(
            (  0,   0,   0,  # 0: Black  — ideal (preserves grayscale midpoint)
             255, 255, 255,  # 1: White  — ideal (preserves grayscale midpoint)
             207, 212,   4,  # 2: Yellow — calibrated (measured on panel)
             150,  28,  23,  # 3: Red    — calibrated
               0,   0,   0,  # 4: unused slot (same as Black)
              12,  84, 172,  # 5: Blue   — calibrated
              29,  90,  72)  # 6: Green  — calibrated
            + (0, 0, 0) * 249
        )

        imwidth, imheight = image.size
        if imwidth == self.width and imheight == self.height:
            image_temp = image
        elif imwidth == self.height and imheight == self.width:
            # Landscape → portrait rotation
            image_temp = image.rotate(90, expand=True)
        else:
            logger.warning(
                "Invalid image dimensions: %dx%d, expected %dx%d or %dx%d",
                imwidth, imheight, self.width, self.height, self.height, self.width,
            )
            return []

        image_7color = image_temp.convert("RGB").quantize(palette=pal_image)
        buf_7color = bytearray(image_7color.tobytes("raw"))

        buf = [0x00] * (self.width * self.height // 2)
        for idx, i in enumerate(range(0, len(buf_7color), 2)):
            buf[idx] = (buf_7color[i] << 4) + buf_7color[i + 1]
        return buf

    # -------------------------------------------------------------------------
    # Display update
    # -------------------------------------------------------------------------

    def display(self, image: list) -> None:
        """Send pre-processed buffer to display and trigger refresh.

        The buffer is split left/right: each row's first half goes to CS_M
        (left 600 pixels), second half goes to CS_S (right 600 pixels).
        """
        width_half  = self.width // 4   # bytes per half-row  (300)
        width_total = self.width // 2   # bytes per full row  (600)

        epdconfig.digital_write(self.EPD_CS_M_PIN, 0)
        self.SendCommand(0x10)
        for i in range(self.height):
            self.SendData2(image[i * width_total : i * width_total + width_half])
        self.CS_ALL(1)

        epdconfig.digital_write(self.EPD_CS_S_PIN, 0)
        self.SendCommand(0x10)
        for i in range(self.height):
            self.SendData2(image[i * width_total + width_half : i * width_total + width_total])
        self.CS_ALL(1)

        self.TurnOnDisplay()

    def Clear(self, color: int = 0x11) -> None:
        """Fill display with a solid color (default 0x11 = white|white)."""
        width_half = self.width // 4   # 300 bytes per half-row

        epdconfig.digital_write(self.EPD_CS_M_PIN, 0)
        self.SendCommand(0x10)
        for _ in range(self.height):
            self.SendData2([color] * width_half)
        self.CS_ALL(1)

        epdconfig.digital_write(self.EPD_CS_S_PIN, 0)
        self.SendCommand(0x10)
        for _ in range(self.height):
            self.SendData2([color] * width_half)
        self.CS_ALL(1)

        self.TurnOnDisplay()

    def sleep(self) -> None:
        self.CS_ALL(0)
        self.SendCommand(0x07)   # DEEP_SLEEP
        self.SendData(0xA5)
        self.CS_ALL(1)

        epdconfig.delay_ms(2000)
        epdconfig.module_exit()

### END OF FILE ###

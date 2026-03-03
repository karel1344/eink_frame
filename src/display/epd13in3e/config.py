# *****************************************************************************
# * | File        :   epdconfig_13in3e.py
# * | Function    :   Hardware config for Waveshare 13.3" Spectra 6 (epd13in3e)
# * | Info        :   Uses Waveshare DEV_Config C shared library (.so)
# *                   Dual CS: EPD_CS_M_PIN=8 (left), EPD_CS_S_PIN=7 (right)
# *****************************************************************************

import os
import sys
import time
import logging
from ctypes import cdll, c_ubyte, c_void_p, POINTER

logger = logging.getLogger(__name__)

# Pin definitions
EPD_CS_M_PIN  = 8
EPD_CS_S_PIN  = 7
EPD_DC_PIN    = 25
EPD_RST_PIN   = 17
EPD_BUSY_PIN  = 24
EPD_PWR_PIN   = 18

# Load the C shared library
_lib = None

def _load_library():
    global _lib
    if _lib is not None:
        return _lib

    find_dirs = [
        os.path.dirname(os.path.realpath(__file__)),
        '/usr/local/lib',
        '/usr/lib',
    ]

    # Detect Raspberry Pi 5 (bcm2712) vs older Pi
    _is_pi5 = False
    try:
        with open('/proc/cpuinfo', 'r') as f:
            if 'BCM2712' in f.read():
                _is_pi5 = True
    except OSError:
        pass

    val = 64
    try:
        import struct
        val = struct.calcsize('P') * 8
    except Exception:
        pass

    for find_dir in find_dirs:
        if _is_pi5:
            so_name = f'DEV_Config_{val}_w.so'
        else:
            so_name = f'DEV_Config_{val}_b.so'
        so_path = os.path.join(find_dir, so_name)
        if os.path.exists(so_path):
            _lib = cdll.LoadLibrary(so_path)
            logger.debug("Loaded %s", so_path)
            return _lib

    raise RuntimeError(
        f"Cannot find DEV_Config_{{64/32}}_{{b/w}}.so in {find_dirs}"
    )


def digital_write(pin, value):
    _load_library()
    _lib.DEV_Digital_Write(pin, value)


def digital_read(pin):
    _load_library()
    return _lib.DEV_Digital_Read(pin)


def delay_ms(delaytime):
    time.sleep(delaytime / 1000.0)


def spi_writebyte(value):
    """Send a single byte over SPI (value is an integer)."""
    _load_library()
    _lib.DEV_SPI_SendData(c_ubyte(value))


def spi_writebyte2(buf, length):
    """Send a buffer of bytes over SPI."""
    _load_library()
    arr = (c_ubyte * length)(*buf)
    _lib.DEV_SPI_SendnData(arr, length)


def module_init():
    _load_library()
    _lib.DEV_ModuleInit()


def module_exit():
    _load_library()
    _lib.DEV_ModuleExit()

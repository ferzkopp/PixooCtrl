"""
Pixoo 16x16 Bluetooth control library.

Based on the Divoom Pixoo Bluetooth Classic (RFCOMM) protocol.
Original work: virtualabs/pixoo-client, letter-t/pixoo-infoapp.
Protocol docs: RomRider/node-divoom-timebox-evo/PROTOCOL.md
"""

import json
import socket
from datetime import datetime
from math import ceil, log2
from pathlib import Path
from time import sleep

from PIL import Image


class Pixoo:
    """Control a Divoom Pixoo 16x16 over Bluetooth RFCOMM."""

    SCREEN_SIZE = 16

    # Protocol commands
    CMD_SET_BRIGHTNESS = 0x74
    CMD_SET_IMAGE = 0x44
    CMD_SET_ANIMATION = 0x49
    CMD_SET_COLOR = 0x6F
    CMD_SET_MODE = 0x45
    CMD_SET_TIME = 0x18

    # Box modes
    MODE_CLOCK = 0
    MODE_TEMP = 1
    MODE_COLOR = 2
    MODE_SPECIAL = 3

    def __init__(self, mac_address: str, port: int = 1):
        self.mac_address = mac_address
        self.port = port
        self._sock: socket.socket | None = None
        # Internal 16x16 pixel buffer: list of (r, g, b) tuples
        self._framebuffer = [
            (0, 0, 0) for _ in range(self.SCREEN_SIZE * self.SCREEN_SIZE)
        ]

    # ── Connection ─────────────────────────────────────────────────

    def connect(self):
        """Open Bluetooth RFCOMM connection to the Pixoo."""
        self._sock = socket.socket(
            socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM
        )
        self._sock.connect((self.mac_address, self.port))
        sleep(0.5)

    def disconnect(self):
        """Close the Bluetooth connection."""
        if self._sock:
            self._sock.close()
            self._sock = None

    @property
    def is_connected(self) -> bool:
        return self._sock is not None

    # ── Low-level protocol ─────────────────────────────────────────

    def _checksum(self, frame: list[int]) -> int:
        return sum(frame[1:]) & 0xFFFF

    def _encode_frame(self, cmd: int, args: list[int]) -> bytes:
        payload_size = len(args) + 3
        header = [0x01, payload_size & 0xFF, (payload_size >> 8) & 0xFF, cmd]
        frame = header + args
        cs = self._checksum(frame)
        suffix = [cs & 0xFF, (cs >> 8) & 0xFF, 0x02]
        return bytes(frame + suffix)

    def _send(self, cmd: int, args: list[int]):
        if not self._sock:
            raise ConnectionError("Not connected. Call connect() first.")
        data = self._encode_frame(cmd, args)
        self._sock.send(data)

    # ── High-level commands ────────────────────────────────────────

    def set_brightness(self, brightness: int):
        """Set display brightness (0–100)."""
        brightness = max(0, min(100, brightness))
        self._send(self.CMD_SET_BRIGHTNESS, [brightness])

    def set_color(self, r: int, g: int, b: int):
        """Fill the display with a solid color."""
        self._send(self.CMD_SET_COLOR, [r & 0xFF, g & 0xFF, b & 0xFF])

    def set_mode(self, mode: int, visual: int = 0, option: int = 0):
        """Switch box mode (clock, temp, color, special)."""
        self._send(self.CMD_SET_MODE, [mode & 0xFF, visual & 0xFF, option & 0xFF])

    def set_time(self, dt: datetime | None = None):
        """Set the device clock. Defaults to current local time."""
        if dt is None:
            dt = datetime.now()
        self._send(self.CMD_SET_TIME, [
            dt.year % 100,
            dt.year // 100,
            dt.month,
            dt.day,
            dt.hour,
            dt.minute,
            dt.second,
        ])

    # ── Pixel buffer operations ────────────────────────────────────

    def clear(self, color: tuple[int, int, int] = (0, 0, 0)):
        """Clear the pixel buffer to a single color."""
        self._framebuffer = [
            color for _ in range(self.SCREEN_SIZE * self.SCREEN_SIZE)
        ]

    def set_pixel(self, x: int, y: int, r: int, g: int, b: int):
        """Set a single pixel in the buffer. Call show() to send to device."""
        if 0 <= x < self.SCREEN_SIZE and 0 <= y < self.SCREEN_SIZE:
            self._framebuffer[x + y * self.SCREEN_SIZE] = (r & 0xFF, g & 0xFF, b & 0xFF)

    def get_pixel(self, x: int, y: int) -> tuple[int, int, int]:
        """Get pixel color from the buffer."""
        if 0 <= x < self.SCREEN_SIZE and 0 <= y < self.SCREEN_SIZE:
            return self._framebuffer[x + y * self.SCREEN_SIZE]
        return (0, 0, 0)

    def fill_rect(self, x: int, y: int, w: int, h: int, r: int, g: int, b: int):
        """Fill a rectangle in the pixel buffer."""
        for py in range(y, min(y + h, self.SCREEN_SIZE)):
            for px in range(x, min(x + w, self.SCREEN_SIZE)):
                self.set_pixel(px, py, r, g, b)

    def show(self):
        """Send the current pixel buffer to the Pixoo display."""
        # Build PIL image from framebuffer
        img = Image.new("RGB", (self.SCREEN_SIZE, self.SCREEN_SIZE))
        for y in range(self.SCREEN_SIZE):
            for x in range(self.SCREEN_SIZE):
                img.putpixel((x, y), self._framebuffer[x + y * self.SCREEN_SIZE])
        self._send_image(img)

    # ── Image encoding & sending ───────────────────────────────────

    def _encode_image(self, img: Image.Image) -> tuple[int, list[int], list[int]]:
        """Encode a 16x16 RGB image into Divoom palette + pixel format."""
        w, h = img.size
        if w != self.SCREEN_SIZE or h != self.SCREEN_SIZE:
            img = img.resize((self.SCREEN_SIZE, self.SCREEN_SIZE))
        img = img.convert("RGB")

        pixels = []
        palette = []
        for y in range(self.SCREEN_SIZE):
            for x in range(self.SCREEN_SIZE):
                color = img.getpixel((x, y))[:3]
                if color not in palette:
                    palette.append(color)
                pixels.append(palette.index(color))

        nb_colors = len(palette)
        if nb_colors < 2:
            bitwidth = 1
        else:
            bitwidth = ceil(log2(nb_colors))

        # Encode pixel indices as a bitstream
        encoded_pixels = []
        encoded_byte = ""
        for idx in pixels:
            encoded_byte = bin(idx)[2:].rjust(bitwidth, "0") + encoded_byte
            if len(encoded_byte) >= 8:
                encoded_pixels.append(encoded_byte[-8:])
                encoded_byte = encoded_byte[:-8]
        if encoded_byte:
            encoded_pixels.append(encoded_byte.ljust(8, "0"))

        pixel_data = [int(b, 2) for b in encoded_pixels]
        palette_data = []
        for r, g, b in palette:
            palette_data.extend([r, g, b])

        return nb_colors, palette_data, pixel_data

    def _send_image(self, img: Image.Image):
        """Encode and send a single image to the display."""
        nb_colors, palette, pixel_data = self._encode_image(img)
        frame_size = 7 + len(pixel_data) + len(palette)
        frame_header = [
            0xAA,
            frame_size & 0xFF,
            (frame_size >> 8) & 0xFF,
            0,
            0,
            0,
            nb_colors,
        ]
        frame = frame_header + palette + pixel_data
        prefix = [0x00, 0x0A, 0x0A, 0x04]
        self._send(self.CMD_SET_IMAGE, prefix + frame)

    def draw_image(self, filepath: str):
        """Load an image file and send it to the display."""
        img = Image.open(filepath).convert("RGB")
        self._send_image(img)

    def draw_pil_image(self, img: Image.Image):
        """Send a PIL Image directly to the display."""
        self._send_image(img.convert("RGB"))

    def draw_gif(self, filepath: str, speed: int = 100):
        """Send an animated GIF to the display."""
        anim = Image.open(filepath)
        frames = []
        timecode = 0
        for n in range(getattr(anim, "n_frames", 1)):
            anim.seek(n)
            nb_colors, palette, pixel_data = self._encode_image(
                anim.convert(mode="RGB")
            )
            frame_size = 7 + len(pixel_data) + len(palette)
            frame_header = [
                0xAA,
                frame_size & 0xFF,
                (frame_size >> 8) & 0xFF,
                timecode & 0xFF,
                (timecode >> 8) & 0xFF,
                0,
                nb_colors,
            ]
            frames.extend(frame_header + palette + pixel_data)
            timecode += speed

        # Send in chunks of 200 bytes
        total_size = len(frames)
        nchunks = ceil(total_size / 200.0)
        for i in range(nchunks):
            chunk_header = [total_size & 0xFF, (total_size >> 8) & 0xFF, i]
            chunk_data = frames[i * 200 : (i + 1) * 200]
            self._send(self.CMD_SET_ANIMATION, chunk_header + chunk_data)

    # ── Config file helpers ────────────────────────────────────────

    @classmethod
    def from_config(cls, config_path: str = "pixoo_config.json") -> "Pixoo":
        """Create a Pixoo instance from a saved config file."""
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(
                f"{config_path} not found. Run find_and_pair_pixoo.ps1 first."
            )
        with open(path, "r") as f:
            config = json.load(f)
        return cls(
            mac_address=config["mac_address"],
            port=config.get("bt_port", 1),
        )

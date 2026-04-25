"""
Pixoo 16x16 Bluetooth control library.

Based on the Divoom Pixoo Bluetooth Classic (RFCOMM) protocol.
Original work: virtualabs/pixoo-client, letter-t/pixoo-infoapp.
Protocol docs: RomRider/node-divoom-timebox-evo/PROTOCOL.md
"""

import json
import os
import socket
from datetime import datetime
from math import ceil, log2
from pathlib import Path
from time import sleep

from PIL import Image

# Default config path (overridable via PIXOO_CONFIG env var or from_config arg)
DEFAULT_CONFIG_PATH = "pixoo_config.json"

# Default socket connect timeout (seconds). Prevents indefinite hangs when the
# device is powered off or out of range.
DEFAULT_CONNECT_TIMEOUT = 8.0
# I/O timeout once connected. Bluetooth Classic writes are usually fast, but a
# disappearing peer can otherwise wedge a send().
DEFAULT_IO_TIMEOUT = 5.0


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

    def __init__(
        self,
        mac_address: str,
        port: int = 1,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        io_timeout: float | None = DEFAULT_IO_TIMEOUT,
    ):
        self.mac_address = mac_address
        self.port = port
        self.connect_timeout = connect_timeout
        self.io_timeout = io_timeout
        self._sock: socket.socket | None = None
        # Internal pixel buffer: contiguous RGB byte triples, row-major.
        # Using a bytearray makes show() ~10x faster than a list of tuples
        # and lets us use Image.frombytes() directly.
        self._framebuffer = bytearray(self.SCREEN_SIZE * self.SCREEN_SIZE * 3)

    # ── Connection ─────────────────────────────────────────────────

    def connect(self):
        """Open Bluetooth RFCOMM connection to the Pixoo.

        Sets a connect timeout so an unreachable device fails fast instead
        of hanging forever, and cleans up the socket on any failure.
        """
        sock = socket.socket(
            socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM
        )
        try:
            sock.settimeout(self.connect_timeout)
            sock.connect((self.mac_address, self.port))
            # After connect, switch to the (usually longer) I/O timeout.
            sock.settimeout(self.io_timeout)
            # Brief settle delay before issuing the first command — some
            # firmware revisions drop the next packet otherwise.
            sleep(0.5)
        except OSError:
            try:
                sock.close()
            except OSError:
                pass
            raise
        self._sock = sock

    def disconnect(self):
        """Close the Bluetooth connection. Idempotent and exception-safe."""
        sock = self._sock
        self._sock = None
        if sock is None:
            return
        try:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                # Half-open / already-closed sockets raise here; ignore.
                pass
            sock.close()
        except OSError:
            pass

    @property
    def is_connected(self) -> bool:
        """Whether an RFCOMM socket is currently open."""
        return self._sock is not None

    def __enter__(self) -> "Pixoo":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.disconnect()

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
        brightness = max(0, min(100, int(brightness)))
        self._send(self.CMD_SET_BRIGHTNESS, [brightness])

    def set_color(self, r: int, g: int, b: int):
        """Fill the display with a solid color (each channel 0–255)."""
        self._send(self.CMD_SET_COLOR, [r & 0xFF, g & 0xFF, b & 0xFF])

    def set_mode(self, mode: int, visual: int = 0, option: int = 0):
        """Switch box mode (clock, temp, color, special)."""
        self._send(self.CMD_SET_MODE, [mode & 0xFF, visual & 0xFF, option & 0xFF])

    def set_time(self, dt: datetime | None = None):
        """Set the device clock. Defaults to current local time.

        The Divoom protocol encodes the year as two bytes: ``year % 100``
        (years-into-century) followed by ``year // 100`` (century).
        Decoding is unambiguous on the device for any valid Gregorian year,
        so 1926 → (26, 19) and 2026 → (26, 20). We require a 4-digit year
        in the supported range to avoid surprising callers.
        """
        if dt is None:
            dt = datetime.now()
        if not 0 <= dt.year <= 9999:
            raise ValueError(
                f"Year {dt.year} outside protocol range (0–9999)"
            )
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
        r, g, b = color
        triplet = bytes((r & 0xFF, g & 0xFF, b & 0xFF))
        self._framebuffer[:] = triplet * (self.SCREEN_SIZE * self.SCREEN_SIZE)

    def set_pixel(self, x: int, y: int, r: int, g: int, b: int):
        """Set a single pixel in the buffer. Call show() to send to device."""
        if 0 <= x < self.SCREEN_SIZE and 0 <= y < self.SCREEN_SIZE:
            i = (x + y * self.SCREEN_SIZE) * 3
            self._framebuffer[i] = r & 0xFF
            self._framebuffer[i + 1] = g & 0xFF
            self._framebuffer[i + 2] = b & 0xFF

    def get_pixel(self, x: int, y: int) -> tuple[int, int, int]:
        """Get pixel color from the buffer."""
        if 0 <= x < self.SCREEN_SIZE and 0 <= y < self.SCREEN_SIZE:
            i = (x + y * self.SCREEN_SIZE) * 3
            return (
                self._framebuffer[i],
                self._framebuffer[i + 1],
                self._framebuffer[i + 2],
            )
        return (0, 0, 0)

    def fill_rect(self, x: int, y: int, w: int, h: int, r: int, g: int, b: int):
        """Fill a rectangle in the pixel buffer."""
        for py in range(y, min(y + h, self.SCREEN_SIZE)):
            for px in range(x, min(x + w, self.SCREEN_SIZE)):
                self.set_pixel(px, py, r, g, b)

    def show(self):
        """Send the current pixel buffer to the Pixoo display."""
        img = Image.frombytes(
            "RGB",
            (self.SCREEN_SIZE, self.SCREEN_SIZE),
            bytes(self._framebuffer),
        )
        self._send_image(img)

    # ── Image encoding & sending ───────────────────────────────────

    def _encode_image(
        self, img: Image.Image
    ) -> tuple[int, list[int], list[int]]:
        """Encode a 16x16 RGB image into Divoom palette + pixel format.

        Returns (nb_colors, palette_bytes, pixel_bytes). Pixel indices are
        packed LSB-first: the first pixel occupies the lowest ``bitwidth``
        bits of the first byte.
        """
        w, h = img.size
        if w != self.SCREEN_SIZE or h != self.SCREEN_SIZE:
            img = img.resize((self.SCREEN_SIZE, self.SCREEN_SIZE))
        if img.mode != "RGB":
            img = img.convert("RGB")

        # Build palette and per-pixel index list. Use a dict for O(1) lookup
        # instead of palette.index() (O(n) per call).
        raw = img.tobytes()  # length = N * 3
        palette: list[tuple[int, int, int]] = []
        palette_index: dict[tuple[int, int, int], int] = {}
        pixels: list[int] = []
        for i in range(0, len(raw), 3):
            color = (raw[i], raw[i + 1], raw[i + 2])
            idx = palette_index.get(color)
            if idx is None:
                idx = len(palette)
                palette_index[color] = idx
                palette.append(color)
            pixels.append(idx)

        nb_colors = len(palette)
        bitwidth = 1 if nb_colors < 2 else ceil(log2(nb_colors))
        mask = (1 << bitwidth) - 1

        # Pack pixel indices LSB-first using a bit accumulator. For the
        # 16x16 display every supported bitwidth (1..8) divides 256 bits
        # evenly, so the trailing partial-byte case never triggers in
        # practice — but we still flush it for correctness.
        encoded_pixels: list[int] = []
        acc = 0
        acc_bits = 0
        for idx in pixels:
            acc |= (idx & mask) << acc_bits
            acc_bits += bitwidth
            while acc_bits >= 8:
                encoded_pixels.append(acc & 0xFF)
                acc >>= 8
                acc_bits -= 8
        if acc_bits > 0:
            encoded_pixels.append(acc & 0xFF)

        palette_data: list[int] = []
        for r, g, b in palette:
            palette_data.append(r)
            palette_data.append(g)
            palette_data.append(b)

        return nb_colors, palette_data, encoded_pixels

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
        path = Path(filepath)
        if not path.is_file():
            raise FileNotFoundError(f"Image file not found: {filepath}")
        img = Image.open(path).convert("RGB")
        self._send_image(img)

    def draw_pil_image(self, img: Image.Image):
        """Send a PIL Image directly to the display."""
        self._send_image(img.convert("RGB"))

    def draw_gif(self, filepath: str, speed: int = 100):
        """Send an animated GIF to the display."""
        path = Path(filepath)
        if not path.is_file():
            raise FileNotFoundError(f"GIF file not found: {filepath}")
        anim = Image.open(path)
        frames: list[int] = []
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
    def from_config(cls, config_path: str | None = None) -> "Pixoo":
        """Create a Pixoo instance from a saved config file.

        Resolution order for the path:
          1. Explicit ``config_path`` argument
          2. ``PIXOO_CONFIG`` environment variable
          3. ``pixoo_config.json`` in the current working directory
        """
        resolved = (
            config_path
            or os.environ.get("PIXOO_CONFIG")
            or DEFAULT_CONFIG_PATH
        )
        path = Path(resolved)
        if not path.is_file():
            raise FileNotFoundError(
                f"Pixoo config not found at {resolved!s}. "
                "Run setup.ps1 on Windows or setup.sh on Linux first, "
                "or set PIXOO_CONFIG to point at an existing file."
            )
        try:
            with open(path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Pixoo config at {resolved!s} is not valid JSON: {exc}"
            ) from exc

        if not isinstance(config, dict):
            raise ValueError(
                f"Pixoo config at {resolved!s} must be a JSON object."
            )

        try:
            mac_address = config["mac_address"]
        except KeyError as exc:
            raise ValueError(
                f"Pixoo config at {resolved!s} is missing required key "
                f"{exc.args[0]!r}."
            ) from exc

        if not isinstance(mac_address, str) or not mac_address:
            raise ValueError(
                f"Pixoo config at {resolved!s}: 'mac_address' must be a "
                "non-empty string."
            )

        port = config.get("bt_port", 1)
        if not isinstance(port, int):
            raise ValueError(
                f"Pixoo config at {resolved!s}: 'bt_port' must be an integer."
            )

        return cls(mac_address=mac_address, port=port)

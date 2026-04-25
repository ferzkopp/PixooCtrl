"""
On-screen simulator for the PixooCtrl demos.

Opens a Tk window that mimics the Divoom Pixoo 16x16 hardware: the same
plastic bezel, LED grid layout and soft glow used by ``gen_previews.py``
for the README screenshots, but updated in real time so people without
a physical device can still see the demos run.

Used by ``demo_runner.DemoRunner`` when the user passes ``--simulate``.

The compositor is intentionally simpler than ``gen_previews.render_panel``
— it skips the per-pixel Python screen-blend (too slow for 30 fps) and
instead uses ``PIL.ImageChops.screen`` on a NEAREST-upscaled + blurred
copy of the 16x16 frame to fake the LED halo.
"""

from __future__ import annotations

from typing import Optional

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageTk

from gen_previews import (
    BEZEL_SIZE,
    CELL_BG,
    CELL_SIZE,
    INNER_MARGIN,
    LED_PAD,
    make_bezel,
)


# Glow blur radius (pixels) applied to the upscaled frame before screen-blend.
# Larger = softer / more bloom, smaller = sharper LEDs.
GLOW_BLUR_RADIUS = 4
# Glow intensity (0.0–1.0): the blurred frame is multiplied by this before
# being screen-blended onto the bezel. Lower = more subtle halo.
GLOW_INTENSITY = 0.55


def _build_base_panel() -> Image.Image:
    """Return the bezel with all 256 cells pre-filled to CELL_BG.

    Drawing the dark cell backgrounds is invariant across frames, so we
    do it once at startup and copy from this image every frame.
    """
    base = make_bezel().convert("RGB")
    d = ImageDraw.Draw(base)
    for gy in range(16):
        for gx in range(16):
            cx = INNER_MARGIN + gx * CELL_SIZE
            cy = INNER_MARGIN + gy * CELL_SIZE
            d.rectangle(
                (cx, cy, cx + CELL_SIZE - 1, cy + CELL_SIZE - 1),
                fill=CELL_BG,
            )
    return base


def _build_glow_canvas_size() -> tuple[int, int, int, int]:
    """Return (left, top, width, height) of the LED panel area inside the bezel."""
    panel_px = CELL_SIZE * 16
    return (INNER_MARGIN, INNER_MARGIN, panel_px, panel_px)


class Simulator:
    """A Tk window that displays successive 16x16 demo frames.

    Lifecycle::

        sim = Simulator("plasma")
        while not sim.closed:
            sim.show_frame(img16)
            sim.pump()
        sim.close()

    The class is deliberately small — the demo runner already owns the
    main loop, frame pacing and shutdown signal handling. We just push
    pixels into a Label and pump the Tk event queue once per frame so
    the window stays responsive.
    """

    def __init__(self, name: str) -> None:
        # Importing tkinter lazily means headless environments (CI, the
        # README preview generator) don't pay for it just to import
        # demo_runner.
        import tkinter as tk

        self._tk = tk
        self._base_panel = _build_base_panel()
        self._panel_box = _build_glow_canvas_size()
        self._led_size = CELL_SIZE - 2 * LED_PAD

        self._root = tk.Tk()
        self._root.title(f"PixooCtrl simulator — {name}")
        self._root.configure(bg="black")
        # Disable resizing so the bezel always renders at native size.
        self._root.resizable(False, False)
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Seed the label with the unlit bezel so the window has correct
        # dimensions before the first frame arrives.
        self._photo = ImageTk.PhotoImage(self._base_panel)
        self._label = tk.Label(
            self._root, image=self._photo, bd=0, bg="black"
        )
        self._label.pack()

        self._closed = False
        # Force an initial draw so the window appears immediately.
        self._root.update()

    # ── Public API ────────────────────────────────────────────────

    @property
    def closed(self) -> bool:
        """True once the user has closed the window."""
        return self._closed

    def show_frame(self, frame16: Image.Image) -> None:
        """Render ``frame16`` (a 16x16 PIL image) onto the bezel."""
        if self._closed:
            return
        if frame16.size != (16, 16):
            frame16 = frame16.resize((16, 16), Image.LANCZOS)
        if frame16.mode != "RGB":
            frame16 = frame16.convert("RGB")

        composite = self._compose(frame16)
        # Hold a reference on self so Tk doesn't garbage-collect the image
        # mid-display (a classic Tk gotcha that shows up as a blank window).
        self._photo = ImageTk.PhotoImage(composite)
        self._label.configure(image=self._photo)

    def pump(self) -> None:
        """Process pending Tk events. Cheap; safe to call every frame."""
        if self._closed:
            return
        try:
            self._root.update()
        except self._tk.TclError:
            # Window was destroyed between pumps (e.g. via the OS close
            # button on some platforms) — treat as a graceful close.
            self._closed = True

    def close(self) -> None:
        """Tear down the Tk window. Idempotent."""
        if self._closed:
            return
        self._closed = True
        try:
            self._root.destroy()
        except self._tk.TclError:
            pass

    # ── Internals ─────────────────────────────────────────────────

    def _on_close(self) -> None:
        self._closed = True
        try:
            self._root.destroy()
        except self._tk.TclError:
            pass

    def _compose(self, frame16: Image.Image) -> Image.Image:
        """Build the bezel image with LEDs lit per ``frame16``.

        Strategy:
          1. Start from the cached "bezel + dark cells" base image.
          2. Draw a rounded LED square per non-dark cell (256 cells max,
             but skipping black ones is significantly cheaper for typical
             demo frames).
          3. Build a glow image by NEAREST-upscaling the 16x16 frame to
             the LED panel size, blurring it, and screen-blending it onto
             the bezel inside the panel area.
        """
        out = self._base_panel.copy()
        d = ImageDraw.Draw(out)
        pixels = frame16.load()
        led = self._led_size
        for gy in range(16):
            for gx in range(16):
                r, g, b = pixels[gx, gy]
                if r == 0 and g == 0 and b == 0:
                    # Cell already painted with CELL_BG in the base copy.
                    continue
                cx = INNER_MARGIN + gx * CELL_SIZE + LED_PAD
                cy = INNER_MARGIN + gy * CELL_SIZE + LED_PAD
                d.rounded_rectangle(
                    (cx, cy, cx + led - 1, cy + led - 1),
                    radius=3,
                    fill=(r, g, b),
                )

        # Glow: upscale the tiny frame to the LED panel area, blur it,
        # dim it by GLOW_INTENSITY, then screen-blend onto the bezel
        # inside that area only.
        left, top, w, h = self._panel_box
        glow_small = frame16.resize((w, h), Image.NEAREST)
        glow = glow_small.filter(ImageFilter.GaussianBlur(GLOW_BLUR_RADIUS))
        if GLOW_INTENSITY < 1.0:
            glow = glow.point(lambda v: int(v * GLOW_INTENSITY))
        panel_region = out.crop((left, top, left + w, top + h))
        blended = ImageChops.screen(panel_region, glow)
        out.paste(blended, (left, top))
        return out


def open_simulator(name: str) -> Optional["Simulator"]:
    """Try to open a simulator window; return None if Tk is unavailable.

    Tk is part of the standard library on Windows/macOS but can be
    missing on minimal Linux installs (``apt install python3-tk``). We
    don't want a missing optional dependency to crash a demo on import,
    so we fall back gracefully.
    """
    try:
        return Simulator(name)
    except Exception as e:  # pragma: no cover — environment-dependent
        print(f"  Simulator unavailable ({type(e).__name__}: {e}).")
        return None

"""
Shared infrastructure for the PixooCtrl demo scripts.

Every demo (lava_lamp, plasma, starfield, rain, snake, hello_kitty) used to
re-implement the same boilerplate: argv parsing, SIGINT handling, frame-rate
limiting, periodic FPS reporting, Pixoo connect/disconnect, and preview-mode
PNG dumps. This module centralises all of that so each demo only needs to
provide a per-frame render callable.

Typical usage:

    from demo_runner import DemoRunner, build_arg_parser

    def render(ctx) -> Image.Image:
        ...

    if __name__ == "__main__":
        args = build_arg_parser("Plasma effect").parse_args()
        DemoRunner(
            name="plasma",
            target_fps=30,
            render=render,
        ).run_from_args(args)
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from pixoo import Pixoo

# Shared default brightness for the demo scripts. Individual demos may override
# this on the CLI with --brightness.
DEFAULT_BRIGHTNESS = 65

# How often (in frames) to print an FPS report to stdout.
FPS_REPORT_INTERVAL = 50

# Resilience: when a frame send fails (e.g. transient Bluetooth drop), the
# runner will attempt to reconnect with exponential backoff up to this many
# times before giving up and exiting. Each attempt waits
# RECONNECT_BACKOFF_BASE * 2**(attempt-1) seconds, capped at
# RECONNECT_BACKOFF_MAX.
RECONNECT_MAX_ATTEMPTS = 8
RECONNECT_BACKOFF_BASE = 1.0
RECONNECT_BACKOFF_MAX = 30.0


@dataclass
class FrameContext:
    """Per-frame data passed to the render callback."""

    frame: int          # 0-based frame counter
    t: float            # seconds since the demo started (monotonic)
    dt: float           # nominal frame delta (1 / target_fps)
    state: Any = None   # arbitrary state object the demo may carry around


# A render callback returns the 16x16 PIL.Image to push to the device, or
# None to skip pushing this frame (the runner will still pace and count it).
RenderFn = Callable[[FrameContext], "Image.Image | None"]


def build_arg_parser(description: str) -> argparse.ArgumentParser:
    """Build a standard argument parser for a demo script.

    All demos accept the same flags so users don't have to remember
    per-demo conventions.
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Don't connect to the Pixoo; save preview PNGs locally instead.",
    )
    parser.add_argument(
        "--preview-dir",
        type=Path,
        default=Path("."),
        help="Directory to write preview PNGs into (default: current dir).",
    )
    parser.add_argument(
        "--preview-every",
        type=int,
        default=16,
        metavar="N",
        help="In preview mode, save every Nth frame (default: 16).",
    )
    parser.add_argument(
        "--brightness",
        type=int,
        default=DEFAULT_BRIGHTNESS,
        metavar="0-100",
        help=f"Pixoo brightness (default: {DEFAULT_BRIGHTNESS}).",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=None,
        metavar="N",
        help="Override the demo's default target FPS.",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to pixoo_config.json (overrides PIXOO_CONFIG env var).",
    )
    return parser


@dataclass
class DemoRunner:
    """Runs a frame-based demo against the Pixoo (or in preview mode).

    The render callable receives a FrameContext and returns the PIL Image
    to display, or None to skip pushing this frame. The runner handles:

      * SIGINT (Ctrl+C) — clean shutdown via a `running` flag
      * Frame pacing via time.monotonic()
      * Periodic FPS reporting to stdout
      * Pixoo connect / disconnect / blackout on exit
      * Preview-mode PNG dumps
    """

    name: str
    target_fps: float
    render: RenderFn
    state_factory: Callable[[], Any] | None = None
    setup_message: str | None = None  # printed once at start
    _running: bool = field(default=True, init=False)

    # ── Public entry points ────────────────────────────────────────

    def run_from_args(self, args: argparse.Namespace) -> None:
        """Run using the standard argparse Namespace from build_arg_parser()."""
        if args.fps is not None and args.fps > 0:
            self.target_fps = float(args.fps)
        self.run(
            preview=args.preview,
            preview_dir=args.preview_dir,
            preview_every=args.preview_every,
            brightness=args.brightness,
            config_path=args.config,
        )

    def run(
        self,
        preview: bool = False,
        preview_dir: Path = Path("."),
        preview_every: int = 16,
        brightness: int = DEFAULT_BRIGHTNESS,
        config_path: str | None = None,
    ) -> None:
        """Run the demo loop until interrupted.

        In preview mode no Bluetooth connection is opened and every Nth
        frame is written to ``preview_dir`` as a PNG. Otherwise the demo
        connects to the Pixoo (loading config from ``config_path`` or the
        default location), pushes each frame, and blacks out the display
        on shutdown.
        """
        if self.target_fps <= 0:
            raise ValueError("target_fps must be > 0")
        frame_delay = 1.0 / self.target_fps

        # SIGINT handler — set the flag, never re-raise.
        def _handle_signal(_sig: int, _frame: Any) -> None:
            self._running = False

        signal.signal(signal.SIGINT, _handle_signal)
        # SIGTERM on POSIX so `kill` also stops cleanly. Windows raises
        # ValueError trying to install SIGTERM, so guard it.
        if hasattr(signal, "SIGTERM"):
            try:
                signal.signal(signal.SIGTERM, _handle_signal)
            except (ValueError, OSError):
                pass

        pixoo: Pixoo | None = None
        if not preview:
            pixoo = Pixoo.from_config(config_path)
            pixoo.connect()
            pixoo.set_brightness(brightness)
            print(f"Connected to Pixoo at {pixoo.mac_address}")
        else:
            preview_dir.mkdir(parents=True, exist_ok=True)

        state = self.state_factory() if self.state_factory else None

        msg = self.setup_message or f"{self.name} running."
        print(f"{msg} Press Ctrl+C to stop.")

        frame_count = 0
        start_time = time.monotonic()
        last_report = start_time
        try:
            while self._running:
                frame_start = time.monotonic()
                ctx = FrameContext(
                    frame=frame_count,
                    t=frame_start - start_time,
                    dt=frame_delay,
                    state=state,
                )

                img = self.render(ctx)

                if img is not None:
                    if pixoo is not None:
                        if not self._send_frame_resilient(
                            pixoo, img, brightness
                        ):
                            # Reconnect failed permanently; bail out of the loop.
                            break
                    elif preview and frame_count % preview_every == 0:
                        out = preview_dir / f"{self.name}_preview_{frame_count:04d}.png"
                        img.save(out)
                        print(f"  Saved preview frame {frame_count} → {out}")

                frame_count += 1

                # Frame pacing
                elapsed = time.monotonic() - frame_start
                remaining = frame_delay - elapsed
                if remaining > 0:
                    # sleep returns early on signal — that's fine, the loop
                    # condition will catch it on the next iteration.
                    time.sleep(remaining)

                # Periodic FPS report
                if frame_count % FPS_REPORT_INTERVAL == 0:
                    now = time.monotonic()
                    actual_fps = FPS_REPORT_INTERVAL / (now - last_report)
                    last_report = now
                    print(f"  Frame {frame_count}, {actual_fps:.1f} fps")

        finally:
            if pixoo is not None:
                try:
                    pixoo.set_color(0, 0, 0)
                except Exception:
                    # Best-effort blackout; never mask the original error.
                    pass
                pixoo.disconnect()
                print("Disconnected.")

    # ── Resilience helpers ───────────────────────────────────

    def _send_frame_resilient(
        self, pixoo: Pixoo, img: "Image.Image", brightness: int
    ) -> bool:
        """Send a frame, transparently reconnecting on transient errors.

        Returns True if the frame was sent (possibly after a reconnect),
        False if the device could not be recovered and the runner should
        exit. OSError covers ConnectionAbortedError / ConnectionResetError /
        BrokenPipeError / TimeoutError, which are the failure modes seen
        when the Bluetooth peer disappears mid-session.
        """
        try:
            pixoo.draw_pil_image(img)
            return True
        except (OSError, ConnectionError) as e:
            print(f"  Frame send failed ({type(e).__name__}: {e}); reconnecting…")

        # Drop the dead socket before retrying.
        try:
            pixoo.disconnect()
        except Exception:
            pass

        for attempt in range(1, RECONNECT_MAX_ATTEMPTS + 1):
            if not self._running:
                return False
            delay = min(
                RECONNECT_BACKOFF_BASE * (2 ** (attempt - 1)),
                RECONNECT_BACKOFF_MAX,
            )
            # Sleep in small slices so Ctrl+C is responsive during backoff.
            slept = 0.0
            while slept < delay and self._running:
                step = min(0.25, delay - slept)
                time.sleep(step)
                slept += step
            if not self._running:
                return False
            try:
                pixoo.connect()
                pixoo.set_brightness(brightness)
                pixoo.draw_pil_image(img)
                print(f"  Reconnected on attempt {attempt}.")
                return True
            except (OSError, ConnectionError) as e:
                print(
                    f"  Reconnect attempt {attempt}/{RECONNECT_MAX_ATTEMPTS} "
                    f"failed ({type(e).__name__}: {e}); waiting {delay:.1f}s."
                )
                try:
                    pixoo.disconnect()
                except Exception:
                    pass

        print(
            f"  Giving up after {RECONNECT_MAX_ATTEMPTS} reconnect attempts."
        )
        return False

    # ── Hooks for demos with non-frame-uniform behaviour ───────────

    def stop(self) -> None:
        """Ask the runner to exit at the end of the current frame."""
        self._running = False

    @property
    def running(self) -> bool:
        """True until ``stop()`` (or a signal handler) requests shutdown."""
        return self._running


# Convenience for demos that just want `if __name__ == "__main__"` boilerplate.
def main(name: str, description: str, target_fps: float, render: RenderFn,
         state_factory: Callable[[], Any] | None = None) -> None:
    """Parse standard CLI args and run a demo with the given render callback."""
    args = build_arg_parser(description).parse_args()
    DemoRunner(
        name=name,
        target_fps=target_fps,
        render=render,
        state_factory=state_factory,
    ).run_from_args(args)

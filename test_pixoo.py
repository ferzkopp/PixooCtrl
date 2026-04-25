"""
Test script for Pixoo 16x16 Bluetooth control.

Connects to the Pixoo using pixoo_config.json and runs a series of visual tests.
Usage:  .\\.venv\\Scripts\\python.exe test_pixoo.py
"""

import sys
import time

from pixoo import Pixoo


def test_solid_colors(pixoo: Pixoo):
    """Flash red, green, blue across the entire display."""
    print("  Test 1: Solid colors (red -> green -> blue)")
    for name, color in [("Red", (255, 0, 0)), ("Green", (0, 255, 0)), ("Blue", (0, 0, 255))]:
        print(f"    {name}...")
        pixoo.set_color(*color)
        time.sleep(1.5)


def test_brightness(pixoo: Pixoo):
    """Ramp brightness up and down."""
    print("  Test 2: Brightness ramp")
    pixoo.set_color(255, 255, 255)
    for b in [10, 30, 60, 100, 60, 30, 10]:
        print(f"    Brightness: {b}")
        pixoo.set_brightness(b)
        time.sleep(0.8)
    pixoo.set_brightness(60)


def test_individual_pixels(pixoo: Pixoo):
    """Set individual pixels using the framebuffer."""
    print("  Test 3: Individual pixels - diagonal line")
    pixoo.clear()
    for i in range(16):
        pixoo.set_pixel(i, i, 255, 255, 0)  # yellow diagonal
    pixoo.show()
    time.sleep(2)


def test_checkerboard(pixoo: Pixoo):
    """Draw a checkerboard pattern."""
    print("  Test 4: Checkerboard pattern")
    pixoo.clear()
    for y in range(16):
        for x in range(16):
            if (x + y) % 2 == 0:
                pixoo.set_pixel(x, y, 255, 0, 255)  # magenta
            else:
                pixoo.set_pixel(x, y, 0, 255, 255)   # cyan
    pixoo.show()
    time.sleep(2)


def test_rectangles(pixoo: Pixoo):
    """Draw nested colored rectangles."""
    print("  Test 5: Nested rectangles")
    pixoo.clear()
    colors = [
        (255, 0, 0),
        (0, 255, 0),
        (0, 0, 255),
        (255, 255, 0),
        (255, 0, 255),
    ]
    for i, (r, g, b) in enumerate(colors):
        offset = i * 1
        size = 16 - 2 * offset
        if size <= 0:
            break
        pixoo.fill_rect(offset, offset, size, size, r, g, b)
    pixoo.show()
    time.sleep(2)


def test_gradient(pixoo: Pixoo):
    """Draw a red-to-blue horizontal gradient."""
    print("  Test 6: Horizontal gradient")
    pixoo.clear()
    for x in range(16):
        r = int(255 * (15 - x) / 15)
        b = int(255 * x / 15)
        for y in range(16):
            pixoo.set_pixel(x, y, r, 0, b)
    pixoo.show()
    time.sleep(2)


def test_smiley(pixoo: Pixoo):
    """Draw a simple smiley face."""
    print("  Test 7: Smiley face")
    pixoo.clear((30, 30, 0))  # dark yellow background

    # Eyes
    for pos in [(5, 5), (10, 5), (5, 6), (10, 6)]:
        pixoo.set_pixel(*pos, 0, 0, 0)

    # Mouth
    for x in [4, 5, 10, 11]:
        pixoo.set_pixel(x, 10, 0, 0, 0)
    for x in range(5, 11):
        pixoo.set_pixel(x, 11, 0, 0, 0)

    pixoo.show()
    time.sleep(2)


def test_clock_mode(pixoo: Pixoo):
    """Set the device time and switch to the built-in clock display."""
    print("  Test 8: Clock mode (sync time)")
    pixoo.set_time()
    pixoo.set_mode(Pixoo.MODE_CLOCK)
    time.sleep(3)


def main():
    """Run the full test suite end-to-end against the configured device."""
    print("=" * 50)
    print("  Pixoo 16x16 Connection Test")
    print("=" * 50)
    print()

    # Load config
    try:
        pixoo = Pixoo.from_config()
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        print("Run setup.ps1 on Windows or setup.sh on Linux to set up your device.")
        sys.exit(1)

    print(f"Device MAC: {pixoo.mac_address}")
    print(f"BT Port:    {pixoo.port}")
    print()

    # Connect
    print("Connecting...")
    try:
        pixoo.connect()
    except OSError as e:
        print(f"ERROR: Could not connect: {e}")
        print()
        print("Troubleshooting:")
        print("  - Is the Pixoo powered on?")
        print("  - Is it paired in Windows Bluetooth settings?")
        print("  - Is another app (e.g., Divoom app) already connected to it?")
        print("  - Try port 2 if port 1 doesn't work (edit pixoo_config.json)")
        sys.exit(1)

    print("Connected!\n")
    time.sleep(1)

    # Run tests
    tests = [
        test_solid_colors,
        test_brightness,
        test_individual_pixels,
        test_checkerboard,
        test_rectangles,
        test_gradient,
        test_smiley,
        test_clock_mode,
    ]

    for test_fn in tests:
        try:
            test_fn(pixoo)
            print("    OK\n")
        except Exception as e:
            print(f"    FAILED: {e}\n")

    # Cleanup
    print("Tests complete. Leaving clock mode active.")
    pixoo.set_brightness(60)
    pixoo.disconnect()
    print("Disconnected.")


if __name__ == "__main__":
    main()

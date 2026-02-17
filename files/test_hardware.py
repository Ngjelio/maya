#!/usr/bin/env python3
"""
🔧 Hardware Test Script
========================
Tests each hardware component individually.
Run this first to verify everything is working.

Usage:
  python3 test_hardware.py          # Run all tests
  python3 test_hardware.py lcd      # Test LCD only
  python3 test_hardware.py mic      # Test microphone only
  python3 test_hardware.py speaker  # Test speaker only
  python3 test_hardware.py button   # Test HAT button
  python3 test_hardware.py leds     # Test HAT LEDs
  python3 test_hardware.py i2c      # Scan I2C bus
"""

import sys
import os
import time
import subprocess

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"

def ok(msg):
    print(f"  {GREEN}✓{RESET} {msg}")

def fail(msg):
    print(f"  {RED}✗{RESET} {msg}")

def warn(msg):
    print(f"  {YELLOW}⚠{RESET} {msg}")

def header(title):
    print(f"\n{'─'*50}")
    print(f"  {title}")
    print(f"{'─'*50}")


def test_lcd():
    """Test the 3.5" LCD display."""
    header("🖥  LCD Display Test")

    # Check framebuffer
    for fb in ["/dev/fb0", "/dev/fb1"]:
        if os.path.exists(fb):
            ok(f"Framebuffer found: {fb}")
        else:
            warn(f"No framebuffer at {fb}")

    # Check if LCD driver is loaded
    try:
        result = subprocess.run(
            ["dmesg"], capture_output=True, text=True, timeout=5
        )
        if "ili9486" in result.stdout.lower() or "fb_ili9486" in result.stdout.lower():
            ok("ILI9486 LCD driver loaded")
        else:
            warn("ILI9486 driver not detected in dmesg")
    except Exception:
        warn("Could not check dmesg")

    # Try pygame
    try:
        os.environ.setdefault("SDL_VIDEODRIVER", "fbcon")
        import pygame
        pygame.init()
        info = pygame.display.Info()
        ok(f"Pygame display: {info.current_w}x{info.current_h}")

        # Quick color test
        screen = pygame.display.set_mode((480, 320))
        colors = [
            ((255, 0, 0), "Red"),
            ((0, 255, 0), "Green"),
            ((0, 0, 255), "Blue"),
            ((255, 255, 255), "White"),
        ]
        for color, name in colors:
            screen.fill(color)
            pygame.display.flip()
            time.sleep(0.5)
        screen.fill((0, 0, 0))
        pygame.display.flip()
        pygame.quit()
        ok("LCD color test passed")
    except Exception as e:
        fail(f"Pygame test failed: {e}")
        warn("Make sure LCD driver is installed (cd ~/LCD-show && sudo ./LCD35B-show)")


def test_microphone():
    """Test the ReSpeaker 2-Mic HAT microphone."""
    header("🎤  Microphone Test")

    # Check ALSA devices
    try:
        result = subprocess.run(
            ["arecord", "-l"], capture_output=True, text=True, timeout=5
        )
        if "seeed" in result.stdout.lower() or "wm8960" in result.stdout.lower():
            ok("ReSpeaker audio device found")
            for line in result.stdout.strip().split("\n"):
                if "card" in line.lower():
                    print(f"    {line.strip()}")
        else:
            fail("ReSpeaker not in arecord -l output")
            warn("Install driver: cd ~/seeed-voicecard && sudo ./install.sh")
            return
    except Exception as e:
        fail(f"arecord failed: {e}")
        return

    # Record test
    print("\n  Recording 3 seconds... speak now!")
    test_file = "/tmp/test_mic.wav"
    try:
        subprocess.run(
            ["arecord", "-D", "plughw:seeed2micvoicec,0",
             "-f", "S16_LE", "-r", "16000", "-c", "1",
             "-d", "3", "-t", "wav", test_file],
            timeout=10, capture_output=True
        )
        size = os.path.getsize(test_file)
        if size > 1000:
            ok(f"Recorded {size} bytes to {test_file}")
            print(f"    Play with: aplay {test_file}")
        else:
            fail("Recording too small — check microphone")
    except subprocess.TimeoutExpired:
        fail("Recording timed out")
    except Exception as e:
        fail(f"Recording failed: {e}")


def test_speaker():
    """Test speaker/headphone output."""
    header("🔊  Speaker Test")

    try:
        result = subprocess.run(
            ["aplay", "-l"], capture_output=True, text=True, timeout=5
        )
        if "seeed" in result.stdout.lower() or "wm8960" in result.stdout.lower():
            ok("ReSpeaker playback device found")
        else:
            warn("ReSpeaker not in aplay -l")
    except Exception:
        pass

    # TTS test
    import shutil
    if shutil.which("espeak-ng"):
        print("  Speaking test phrase...")
        try:
            subprocess.run(
                ["espeak-ng", "-s", "140", "Hello! The Maya is working."],
                timeout=10
            )
            ok("espeak-ng TTS working")
        except Exception as e:
            fail(f"espeak-ng failed: {e}")
    elif shutil.which("espeak"):
        print("  Speaking test phrase...")
        subprocess.run(["espeak", "Hello! The Maya is working."], timeout=10)
        ok("espeak TTS working")
    else:
        fail("No TTS engine (install espeak-ng)")


def test_button():
    """Test the on-board button on GPIO 17."""
    header("🔘  Button Test (GPIO 17)")

    try:
        import RPi.GPIO as GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(17, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        print("  Press the button on the ReSpeaker HAT (10 second timeout)...")
        start = time.time()
        pressed = False
        while time.time() - start < 10:
            if GPIO.input(17) == 0:
                ok("Button press detected!")
                pressed = True
                break
            time.sleep(0.05)

        if not pressed:
            warn("No button press detected within 10 seconds")

        GPIO.cleanup(17)
    except ImportError:
        fail("RPi.GPIO not available (not running on Pi?)")
    except Exception as e:
        fail(f"Button test failed: {e}")


def test_leds():
    """Test the 3 APA102 LEDs on the ReSpeaker HAT."""
    header("💡  APA102 LED Test")

    try:
        from apa102_pi.driver import apa102
        strip = apa102.APA102(num_led=3, global_brightness=20)

        colors = [
            ((255, 0, 0), "Red"),
            ((0, 255, 0), "Green"),
            ((0, 0, 255), "Blue"),
            ((255, 255, 255), "White"),
        ]

        for (r, g, b), name in colors:
            for i in range(3):
                strip.set_pixel(i, r, g, b)
            strip.show()
            print(f"    LEDs: {name}")
            time.sleep(0.5)

        strip.clear_strip()
        ok("LED test complete")
    except ImportError:
        fail("apa102-pi not installed: pip install apa102-pi")
    except Exception as e:
        fail(f"LED test failed: {e}")
        warn("LEDs may conflict with SPI LCD — this is expected")


def test_i2c():
    """Scan the I2C bus for connected sensors."""
    header("🔌  I2C Bus Scan")

    try:
        result = subprocess.run(
            ["i2cdetect", "-y", "1"],
            capture_output=True, text=True, timeout=5
        )
        print(result.stdout)

        known = {
            "68": "MPU6050 (accel/gyro)",
            "57": "MAX30102 (heart rate)",
            "76": "BME280 (temp/humidity)",
            "77": "BME280 alt / BMP280",
            "5a": "MLX90614 (IR temp)",
            "23": "BH1750 (light)",
            "1a": "WM8960 (audio codec - ReSpeaker)",
        }

        for addr, name in known.items():
            if addr in result.stdout:
                ok(f"Found {name} at 0x{addr}")

    except FileNotFoundError:
        fail("i2cdetect not found: sudo apt install i2c-tools")
    except Exception as e:
        fail(f"I2C scan failed: {e}")


# ─── Main ───────────────────────────────────────────────────
if __name__ == "__main__":
    tests = {
        "lcd": test_lcd,
        "mic": test_microphone,
        "speaker": test_speaker,
        "button": test_button,
        "leds": test_leds,
        "i2c": test_i2c,
    }

    print(f"\n{'='*50}")
    print("  🔧 Hardware Test Suite")
    print(f"{'='*50}")

    if len(sys.argv) > 1:
        name = sys.argv[1].lower()
        if name in tests:
            tests[name]()
        else:
            print(f"Unknown test: {name}")
            print(f"Available: {', '.join(tests.keys())}")
    else:
        for test_fn in tests.values():
            test_fn()

    print(f"\n{'='*50}")
    print("  Done!")
    print(f"{'='*50}\n")

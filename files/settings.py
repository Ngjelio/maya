# ═══════════════════════════════════════════════════════════
#  Maya — Configuration
# ═══════════════════════════════════════════════════════════

import json
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent

CONFIG = {
    # ─── Display: Waveshare 3.5" RPi LCD (B) ───────────────
    "display": {
        "width": 480,
        "height": 320,
        "fps": 30,
        "driver": "fbcp",            # framebuffer copy (SPI LCD)
        "spi_speed": 32000000,       # 32MHz SPI clock
        "backlight_pin": 18,         # GPIO for backlight control
        "auto_dim_minutes": 5,       # dim after inactivity
        "brightness": 100,           # 0-100%
        "rotation": 90,              # 0, 90, 180, 270
    },

    # ─── Audio: ReSpeaker 2-Mic Pi HAT (WM8960) ───────────
    "audio": {
        "card_name": "seeed2micvoicec",
        "sample_rate": 16000,
        "channels": 1,               # mono for STT
        "chunk_size": 8000,          # frames per buffer
        "format": "int16",
        "playback_device": "plughw:seeed2micvoicec,0",
        "capture_device": "plughw:seeed2micvoicec,0",
        "volume": 80,                # 0-100
        # ReSpeaker extras
        "button_gpio": 17,           # on-board user button
        "led_count": 3,              # APA102 RGB LEDs
    },

    # ─── Voice Assistant ───────────────────────────────────
    "voice": {
        "wake_word": "hey maya",
        "companion_name": "Maya",
        "stt_engine": "vosk",
        "model_path": str(BASE_DIR / "models" / "vosk-model-small-en-us"),
        "tts_engine": "espeak-ng",   # offline TTS (fallback: espeak)
        "tts_speed": 140,            # words per minute
        "tts_pitch": 50,             # 0-99
        "language": "en",
        "confidence_threshold": 0.6,
    },

    # ─── Alerts ────────────────────────────────────────────
    "alerts": {
        "emergency_contacts": [],     # phone numbers for SMS alerts
        "fall_cooldown_seconds": 30,
        "inactivity_alert_hours": 4,
        "medication_reminders": [],   # [{"name": "...", "times": ["08:00", "20:00"]}]
    },

    # ─── Sensors (future) ─────────────────────────────────
    "sensors": {
        "mpu6050": {"enabled": False, "i2c_addr": 0x68, "poll_hz": 10},
        "max30102": {"enabled": False, "i2c_addr": 0x57, "poll_hz": 1},
        "bme280": {"enabled": False, "i2c_addr": 0x76, "poll_hz": 0.1},
        "mlx90614": {"enabled": False, "i2c_addr": 0x5A, "poll_hz": 0.5},
    },

    # ─── General ──────────────────────────────────────────
    "general": {
        "log_level": "INFO",
        "data_dir": str(BASE_DIR / "data"),
        "companion_name": "Maya",
    },

    # ─── GPIO Pin Map ─────────────────────────────────────
    #  This documents ALL GPIO usage to prevent conflicts.
    #
    #  Waveshare 3.5" LCD (B) uses:
    #    SPI0: GPIO 7(CE1), 8(CE0), 9(MISO), 10(MOSI), 11(SCLK)
    #    Touch: GPIO 25 (IRQ), uses SPI CE1
    #    Backlight: GPIO 18
    #    Reset: GPIO 27
    #    DC: GPIO 24 (data/command)
    #
    #  ReSpeaker 2-Mic HAT uses:
    #    I2S: GPIO 18(BCLK), 19(LRCLK), 20(DIN), 21(DOUT)
    #    I2C1: GPIO 2(SDA), 3(SCL) — for WM8960 codec
    #    Button: GPIO 17
    #    APA102 LEDs: GPIO 10(MOSI), 11(SCLK) via SPI
    #
    #  ⚠ CONFLICT: GPIO 18 used by BOTH LCD backlight and I2S BCLK
    #  ⚠ CONFLICT: GPIO 10, 11 used by BOTH LCD SPI and APA102 LEDs
    #
    #  SOLUTION: Use pygame framebuffer (not SPI) for display,
    #  or use HDMI+fbcp approach. LEDs disabled when LCD is active.
    #
    "gpio_map": {
        # LCD (active)
        "lcd_dc": 24,
        "lcd_reset": 27,
        "lcd_backlight": 18,
        # ReSpeaker (active)
        "mic_button": 17,
        # I2C bus 1 (shared, for future sensors)
        "i2c_sda": 2,
        "i2c_scl": 3,
        # Available for future use
        "free_gpio": [4, 5, 6, 12, 13, 16, 22, 23, 26],
    },
}


def save_config(filepath=None):
    """Save current config to JSON file."""
    if filepath is None:
        filepath = BASE_DIR / "config" / "settings.json"
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w") as f:
        json.dump(CONFIG, f, indent=2)


def load_config(filepath=None):
    """Load config from JSON file, merging with defaults."""
    if filepath is None:
        filepath = BASE_DIR / "config" / "settings.json"
    filepath = Path(filepath)
    if filepath.exists():
        with open(filepath) as f:
            user_config = json.load(f)
        _deep_merge(CONFIG, user_config)
    return CONFIG


def _deep_merge(base, override):
    """Recursively merge override into base dict."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value

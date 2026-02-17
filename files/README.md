# 🏠 Maya

**A privacy-first Raspberry Pi smart assistant for safety, health monitoring, and voice interaction.**

Everything runs **offline** — no cloud, no data leaves the device.

## Hardware

| Component | Model | Status |
|-----------|-------|--------|
| Computer | Raspberry Pi 4 | ✅ |
| Display | Waveshare SpotPear 3.5" RPi LCD (B) — 480×320, SPI | ✅ |
| Audio | Keyestudio ReSpeaker 2-Mic Pi HAT (WM8960) | ✅ |
| Sensors | MPU6050, MAX30102, BME280, etc. | 🔜 Add later |

## Project Structure

```
maya/
├── main.py                  # 🚀 Run this
├── setup.sh                 # 📦 One-command installer
├── test_hardware.py         # 🔧 Test each component
├── requirements.txt
├── config/
│   ├── __init__.py
│   └── settings.py          # All hardware & software config
├── modules/
│   ├── __init__.py
│   ├── display.py           # Pygame LCD renderer (480×320)
│   ├── voice.py             # Vosk STT + espeak TTS + LEDs + button
│   ├── sensors.py           # I2C sensor hub with auto-detect
│   └── alerts.py            # Emergency & wellness alerts
├── scripts/
│   └── maya.service  # Auto-start on boot
├── models/                  # Vosk speech models (created by setup)
└── data/                    # Logs, alert history (auto-created)
```

## Quick Start

```bash
# 1. Copy project to Pi
scp -r maya/ pi@raspberrypi:~/

# 2. SSH in and run setup
ssh pi@raspberrypi
cd ~/maya
chmod +x setup.sh
./setup.sh

# 3. Install LCD driver (reboots Pi!)
cd ~/LCD-show
sudo ./LCD35B-show 90

# 4. After reboot — test hardware
cd ~/maya
source venv/bin/activate
python3 test_hardware.py

# 5. Run!
python3 main.py --demo      # test mode (no sensors needed)
python3 main.py             # live mode
```

## GPIO Pin Usage

Both the LCD and mic HAT stack on the 40-pin header. Here's the pin map:

| GPIO | Used By | Function |
|------|---------|----------|
| 2 | I2C | SDA (shared: sensors + WM8960) |
| 3 | I2C | SCL (shared) |
| 7 | LCD | SPI CE1 |
| 8 | LCD | SPI CE0 |
| 9 | LCD | SPI MISO |
| 10 | LCD | SPI MOSI |
| 11 | LCD | SPI SCLK |
| 17 | Mic HAT | User button |
| 18 | I2S | BCLK (audio clock) |
| 19 | I2S | LRCLK (left/right) |
| 20 | I2S | DIN (audio data in) |
| 21 | I2S | DOUT (audio data out) |
| 24 | LCD | Data/Command |
| 25 | LCD | Touch IRQ |
| 27 | LCD | Reset |
| **Free** | Available | **4, 5, 6, 12, 13, 16, 22, 23, 26** |

## Voice Commands

Press the **button on the mic HAT** or say **"Hey Maya"** then:

| Say | Response |
|-----|----------|
| "What time is it?" | Current time |
| "What's today?" | Current date |
| "Hello" / "Hi" | Greeting |
| "How are you?" | Friendly response |
| "Help" | List of capabilities |
| "Good morning/evening" | Time-appropriate greeting |
| "Good night" | Goodnight message |
| "Readings" / "Vitals" | Current sensor data |
| "Emergency" | Initiates emergency protocol |
| "Stop" / "Quiet" | Stops listening |

## Auto-Start on Boot

```bash
sudo cp scripts/maya.service /etc/systemd/system/
sudo systemctl enable maya
sudo systemctl start maya

# Check status
sudo systemctl status maya

# View logs
journalctl -u maya -f
```

## Adding Sensors Later

All I2C sensors share 4 wires (connect to GPIO 2, 3 + 3.3V + GND):

```bash
# Check what's connected
i2cdetect -y 1

# Sensors are auto-detected!
# Just wire them up and restart the maya.
```

| Sensor | I2C Addr | What it adds | Price |
|--------|----------|-------------|-------|
| MPU6050 | 0x68 | Fall detection | €3-5 |
| MAX30102 | 0x57 | Heart rate + SpO2 | €5-8 |
| BME280 | 0x76 | Room temp/humidity/pressure | €5 |
| MLX90614 | 0x5A | Body temperature | €8-10 |

## Command Line Options

```bash
python3 main.py              # Full live mode
python3 main.py --demo       # Simulated sensors + windowed display
python3 main.py --no-voice   # No mic/speaker
python3 main.py --no-display # Headless (voice + sensors only)
python3 main.py --debug      # Verbose logging
```

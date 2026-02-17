#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
#  🏠 Maya — Full Setup Script
#  Hardware: RPi 4 + Waveshare 3.5" LCD (B) + ReSpeaker 2-Mic HAT
# ═══════════════════════════════════════════════════════════════════
#
#  IMPORTANT: Run this BEFORE stacking both HATs!
#  The LCD uses SPI pins and the Mic HAT uses I2S pins.
#  They can coexist but drivers must be installed in order.
#
#  Usage:
#    chmod +x setup.sh
#    ./setup.sh
#
# ═══════════════════════════════════════════════════════════════════

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

echo -e "${GREEN}"
echo "  ╔═══════════════════════════════════════════════╗"
echo "  ║   🏠 Maya — Setup        ║"
echo "  ║   RPi 4 + 3.5\" LCD (B) + ReSpeaker 2-Mic    ║"
echo "  ╚═══════════════════════════════════════════════╝"
echo -e "${NC}"

# ─── [1/7] System packages ───────────────────────────────────
echo -e "${YELLOW}[1/7] Installing system dependencies...${NC}"
sudo apt-get update -qq
sudo apt-get install -y \
    python3-pip python3-venv python3-dev \
    libatlas-base-dev libportaudio2 portaudio19-dev libasound2-dev \
    espeak-ng alsa-utils \
    chromium-browser \
    i2c-tools \
    git unzip wget cmake \
    libsdl2-dev libsdl2-ttf-dev \
    python3-pygame \
    xdotool xterm \
    spi-tools

# ─── [2/7] Enable interfaces ────────────────────────────────
echo -e "${YELLOW}[2/7] Enabling SPI, I2C, and I2S interfaces...${NC}"
sudo raspi-config nonint do_spi 0
sudo raspi-config nonint do_i2c 0

# Ensure SPI is enabled in config.txt
if ! grep -q "^dtparam=spi=on" /boot/firmware/config.txt 2>/dev/null && \
   ! grep -q "^dtparam=spi=on" /boot/config.txt 2>/dev/null; then
    CONFIG_FILE="/boot/firmware/config.txt"
    [ ! -f "$CONFIG_FILE" ] && CONFIG_FILE="/boot/config.txt"
    echo "dtparam=spi=on" | sudo tee -a "$CONFIG_FILE"
fi

# ─── [3/7] Waveshare 3.5" LCD (B) driver ────────────────────
echo -e "${YELLOW}[3/7] Installing Waveshare 3.5\" LCD (B) driver...${NC}"
LCD_DIR="$HOME/LCD-show"
if [ ! -d "$LCD_DIR" ]; then
    cd "$HOME"
    git clone https://github.com/waveshareteam/LCD-show.git
    cd LCD-show
    # Don't run LCD35B-show yet — it reboots!
    # We'll configure it after all drivers are installed.
    echo -e "${GREEN}   ✓ LCD driver downloaded${NC}"
    echo -e "${YELLOW}   ⚠ Will activate after all setup is complete${NC}"
else
    echo -e "${GREEN}   ✓ LCD driver already present${NC}"
fi

# ─── [4/7] ReSpeaker 2-Mic HAT driver (WM8960) ─────────────
echo -e "${YELLOW}[4/7] Installing ReSpeaker 2-Mic HAT driver...${NC}"
VOICECARD_DIR="$HOME/seeed-voicecard"
if [ ! -d "$VOICECARD_DIR" ]; then
    cd "$HOME"
    git clone --depth=1 https://github.com/HinTak/seeed-voicecard.git
    cd seeed-voicecard
    sudo ./install.sh
    echo -e "${GREEN}   ✓ ReSpeaker driver installed${NC}"
else
    echo -e "${GREEN}   ✓ ReSpeaker driver already present${NC}"
fi

# ─── [5/7] Python virtual environment ───────────────────────
echo -e "${YELLOW}[5/7] Setting up Python environment...${NC}"
VENV_DIR="$SCRIPT_DIR/venv"
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR" --system-site-packages
fi
source "$VENV_DIR/bin/activate"
pip install --upgrade pip -q
pip install -r "$SCRIPT_DIR/requirements.txt" -q
echo -e "${GREEN}   ✓ Python packages installed${NC}"

# ─── [6/7] Vosk speech model ────────────────────────────────
echo -e "${YELLOW}[6/7] Downloading offline speech recognition model...${NC}"
MODEL_DIR="$SCRIPT_DIR/models"
mkdir -p "$MODEL_DIR"
if [ ! -d "$MODEL_DIR/vosk-model-small-en-us-0.15" ]; then
    cd "$MODEL_DIR"
    wget -q --show-progress https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
    unzip -q vosk-model-small-en-us-0.15.zip
    ln -sf vosk-model-small-en-us-0.15 vosk-model-small-en-us
    rm -f vosk-model-small-en-us-0.15.zip
    echo -e "${GREEN}   ✓ Vosk model ready (~50MB)${NC}"
else
    echo -e "${GREEN}   ✓ Vosk model already present${NC}"
fi

# ─── [7/7] ALSA config for ReSpeaker ────────────────────────
echo -e "${YELLOW}[7/7] Configuring audio defaults...${NC}"
cat > "$HOME/.asoundrc" << 'EOF'
# Default audio through ReSpeaker 2-Mic HAT (WM8960)
pcm.!default {
    type asym
    playback.pcm "speaker"
    capture.pcm "mic"
}

pcm.speaker {
    type plug
    slave {
        pcm "hw:seeed2micvoicec,0"
    }
}

pcm.mic {
    type plug
    slave {
        pcm "hw:seeed2micvoicec,0"
        rate 16000
        channels 1
    }
}
EOF
echo -e "${GREEN}   ✓ Audio configured for ReSpeaker HAT${NC}"

# ─── Summary ────────────────────────────────────────────────
echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✅ Setup complete!${NC}"
echo ""
echo -e "  ${YELLOW}NEXT STEPS:${NC}"
echo ""
echo -e "  1. Activate the LCD driver (will reboot Pi):"
echo -e "     ${GREEN}cd ~/LCD-show && sudo ./LCD35B-show${NC}"
echo ""
echo -e "  2. After reboot, start the maya:"
echo -e "     ${GREEN}cd $SCRIPT_DIR${NC}"
echo -e "     ${GREEN}source venv/bin/activate${NC}"
echo -e "     ${GREEN}python3 main.py --demo${NC}     # test without sensors"
echo -e "     ${GREEN}python3 main.py${NC}             # live mode"
echo ""
echo -e "  3. Test audio separately:"
echo -e "     ${GREEN}arecord -D plughw:seeed2micvoicec -f S16_LE -r 16000 -c 1 -d 5 test.wav${NC}"
echo -e "     ${GREEN}aplay test.wav${NC}"
echo ""
echo -e "  4. Check I2C bus (for future sensors):"
echo -e "     ${GREEN}i2cdetect -y 1${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"

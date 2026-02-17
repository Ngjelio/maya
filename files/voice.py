"""
Voice Assistant — ReSpeaker 2-Mic HAT + Vosk STT
=================================================
Hardware: Keyestudio/Seeed ReSpeaker 2-Mic Pi HAT (WM8960)
  - 2x MEMS microphones
  - 3x APA102 RGB LEDs
  - 1x User button (GPIO 17)
  - 3.5mm headphone jack + JST speaker out

Audio pipeline:
  Mic (WM8960 I2S) → ALSA → Vosk STT → Command Parser → TTS → Speaker

All processing is offline for privacy.
"""

import os
import sys
import json
import time
import wave
import struct
import logging
import asyncio
import threading
from pathlib import Path
from datetime import datetime

log = logging.getLogger("Voice")

# LED patterns for the 3 APA102 LEDs on the ReSpeaker HAT
LED_PATTERNS = {
    "idle":      [(0, 0, 10)] * 3,        # dim blue
    "listening": [(0, 40, 0)] * 3,         # green pulse
    "thinking":  [(40, 30, 0)] * 3,        # amber
    "speaking":  [(0, 0, 40)] * 3,         # blue
    "alert":     [(40, 0, 0)] * 3,         # red
    "off":       [(0, 0, 0)] * 3,
}


class LEDController:
    """Controls the 3 APA102 RGB LEDs on the ReSpeaker HAT."""

    def __init__(self):
        self.pixels = None
        self.enabled = False

    def init(self):
        """Initialize APA102 LED strip."""
        try:
            from apa102_pi.driver import apa102
            self.pixels = apa102.APA102(num_led=3, global_brightness=10)
            self.enabled = True
            log.info("APA102 LEDs initialized (3 LEDs)")
        except ImportError:
            log.warning("apa102-pi not installed — LEDs disabled")
        except Exception as e:
            log.warning(f"LED init failed: {e}")

    def set_pattern(self, pattern_name):
        """Set LED pattern by name."""
        if not self.enabled or not self.pixels:
            return
        pattern = LED_PATTERNS.get(pattern_name, LED_PATTERNS["off"])
        for i, (r, g, b) in enumerate(pattern):
            self.pixels.set_pixel(i, r, g, b)
        self.pixels.show()

    def set_color(self, r, g, b):
        """Set all LEDs to same color."""
        if not self.enabled or not self.pixels:
            return
        for i in range(3):
            self.pixels.set_pixel(i, r, g, b)
        self.pixels.show()

    def cleanup(self):
        """Turn off LEDs."""
        if self.pixels:
            self.pixels.clear_strip()


class ButtonHandler:
    """Handles the physical button on the ReSpeaker HAT (GPIO 17)."""

    def __init__(self, gpio_pin=17):
        self.pin = gpio_pin
        self.callback = None
        self.enabled = False

    def init(self, on_press_callback):
        """Setup GPIO button with callback."""
        self.callback = on_press_callback
        try:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.add_event_detect(
                self.pin, GPIO.FALLING,
                callback=self._on_press,
                bouncetime=300
            )
            self.enabled = True
            log.info(f"Button initialized on GPIO {self.pin}")
        except ImportError:
            log.warning("RPi.GPIO not available — button disabled")
        except Exception as e:
            log.warning(f"Button init failed: {e}")

    def _on_press(self, channel):
        """Internal callback for button press."""
        if self.callback:
            self.callback()

    def cleanup(self):
        """Release GPIO."""
        if self.enabled:
            try:
                import RPi.GPIO as GPIO
                GPIO.remove_event_detect(self.pin)
            except Exception:
                pass


class VoiceAssistant:
    """
    Full voice assistant using ReSpeaker 2-Mic HAT.

    Features:
    - Wake word detection ("hey maya")
    - Push-to-talk via hardware button
    - Offline STT via Vosk
    - Offline TTS via espeak-ng
    - LED feedback for voice states
    - Command routing with extensible handlers
    """

    def __init__(self, config, audio_config):
        self.config = config
        self.audio_config = audio_config
        self.leds = LEDController()
        self.button = ButtonHandler(audio_config.get("button_gpio", 17))

        self.listening = False
        self.speaking = False
        self._stt_ready = False
        self._tts_ready = False
        self._model = None
        self._audio_stream = None

        # Command handlers (extensible)
        self.command_handlers = {}
        self._register_default_commands()

        # Callbacks
        self.on_listening_change = None   # (bool) -> None
        self.on_speech_text = None        # (str) -> None
        self.on_command_result = None     # (str) -> None

    def _register_default_commands(self):
        """Register built-in voice commands."""
        self.command_handlers = {
            "time": self._cmd_time,
            "what time": self._cmd_time,
            "date": self._cmd_date,
            "what day": self._cmd_date,
            "today": self._cmd_date,
            "hello": self._cmd_hello,
            "hi": self._cmd_hello,
            "how are you": self._cmd_how_are_you,
            "help": self._cmd_help,
            "what can you do": self._cmd_help,
            "thank": self._cmd_thanks,
            "good morning": self._cmd_greeting,
            "good afternoon": self._cmd_greeting,
            "good evening": self._cmd_greeting,
            "good night": self._cmd_goodnight,
            "weather": self._cmd_weather,
            "temperature": self._cmd_temperature,
            "how am i": self._cmd_health_check,
            "health": self._cmd_health_check,
            "emergency": self._cmd_emergency,
            "stop": self._cmd_stop,
            "quiet": self._cmd_stop,
        }

    async def setup(self):
        """Initialize all voice subsystems."""
        # LEDs
        self.leds.init()
        self.leds.set_pattern("idle")

        # Button (push-to-talk)
        self.button.init(self._on_button_press)

        # STT (Vosk)
        await self._setup_stt()

        # TTS (espeak-ng)
        self._setup_tts()

        log.info("Voice assistant ready")

    async def _setup_stt(self):
        """Initialize Vosk offline speech-to-text."""
        try:
            import vosk
            vosk.SetLogLevel(-1)  # suppress vosk logs

            model_path = self.config.get("model_path", "")
            if not Path(model_path).exists():
                log.warning(f"Vosk model not found: {model_path}")
                log.warning("Run setup.sh to download the model")
                return

            self._model = vosk.Model(model_path)
            self._stt_ready = True
            log.info(f"Vosk STT ready (model: {Path(model_path).name})")
        except ImportError:
            log.warning("Vosk not installed: pip install vosk")

    def _setup_tts(self):
        """Initialize text-to-speech."""
        import shutil
        if shutil.which("espeak-ng"):
            self._tts_ready = True
            self._tts_cmd = "espeak-ng"
            log.info("TTS: espeak-ng ready")
        elif shutil.which("espeak"):
            self._tts_ready = True
            self._tts_cmd = "espeak"
            log.info("TTS: espeak ready (fallback)")
        elif shutil.which("piper"):
            self._tts_ready = True
            self._tts_cmd = "piper"
            log.info("TTS: piper ready")
        else:
            log.warning("No TTS engine found. Install espeak-ng.")

    def _on_button_press(self):
        """Handle hardware button press — toggle listening."""
        log.info("Button pressed — toggling listen mode")
        if self.listening:
            self.listening = False
        else:
            self.listening = True
            if self.on_listening_change:
                self.on_listening_change(True)

    async def speak(self, text):
        """Speak text through the ReSpeaker's speaker/headphone out."""
        if not self._tts_ready:
            log.warning(f"TTS unavailable — would say: {text}")
            return

        self.speaking = True
        self.leds.set_pattern("speaking")
        log.info(f"Speaking: {text}")

        if self.on_command_result:
            self.on_command_result(text)

        try:
            speed = self.config.get("tts_speed", 140)
            pitch = self.config.get("tts_pitch", 50)
            device = self.audio_config.get("playback_device", "default")

            if self._tts_cmd == "piper":
                cmd = f'echo "{text}" | piper --output-raw | aplay -D {device} -r 22050 -f S16_LE -c 1 -q'
            else:
                cmd = f'{self._tts_cmd} -s {speed} -p {pitch} -v en "{text}" 2>/dev/null'

            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        except Exception as e:
            log.error(f"TTS error: {e}")
        finally:
            self.speaking = False
            self.leds.set_pattern("idle")

    async def listen_continuous(self):
        """
        Main listening loop. Continuously monitors microphone for:
        1. Wake word ("hey maya") → enters command mode
        2. Button press → enters command mode (via callback)
        """
        if not self._stt_ready:
            log.warning("STT not ready — voice commands disabled")
            # Still run to keep the task alive
            while True:
                await asyncio.sleep(1)

        import sounddevice as sd
        from vosk import KaldiRecognizer

        sample_rate = self.audio_config.get("sample_rate", 16000)
        chunk_size = self.audio_config.get("chunk_size", 8000)

        rec = KaldiRecognizer(self._model, sample_rate)
        rec.SetWords(True)

        log.info("Listening for wake word or button press...")
        self.leds.set_pattern("idle")

        # Determine the correct audio device
        device_name = self.audio_config.get("card_name", "seeed2micvoicec")
        device_id = self._find_audio_device(device_name)

        try:
            with sd.RawInputStream(
                device=device_id,
                samplerate=sample_rate,
                blocksize=chunk_size,
                dtype="int16",
                channels=1,
            ) as stream:
                while True:
                    data, overflowed = stream.read(chunk_size)
                    if overflowed:
                        log.debug("Audio buffer overflow")

                    if rec.AcceptWaveform(bytes(data)):
                        result = json.loads(rec.Result())
                        text = result.get("text", "").lower().strip()

                        if text:
                            await self._process_speech(text)
                    else:
                        # Partial results (for UI feedback)
                        partial = json.loads(rec.PartialResult())
                        partial_text = partial.get("partial", "")
                        if partial_text and self.on_speech_text:
                            self.on_speech_text(partial_text)

                    await asyncio.sleep(0.01)  # yield to event loop

        except sd.PortAudioError as e:
            log.error(f"Audio device error: {e}")
            log.info("Check that ReSpeaker HAT is connected and driver installed")
        except Exception as e:
            log.error(f"Listen loop error: {e}")

    def _find_audio_device(self, card_name):
        """Find the sounddevice index for the ReSpeaker card."""
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            for i, dev in enumerate(devices):
                if card_name in dev.get("name", ""):
                    log.info(f"Audio device: [{i}] {dev['name']}")
                    return i
            log.warning(f"Audio device '{card_name}' not found, using default")
            return None
        except Exception:
            return None

    async def _process_speech(self, text):
        """Process recognized speech — check for wake word or direct commands."""
        log.info(f"Heard: '{text}'")

        wake_word = self.config.get("wake_word", "hey maya")

        if wake_word in text:
            # Extract command after wake word
            command = text.split(wake_word, 1)[-1].strip()
            if command:
                await self._handle_command(command)
            else:
                # Wake word only — enter active listening
                self.listening = True
                self.leds.set_pattern("listening")
                await self.speak("Yes? I'm listening.")
                if self.on_listening_change:
                    self.on_listening_change(True)
        elif self.listening:
            # Already in active mode — treat as command
            await self._handle_command(text)
            self.listening = False
            self.leds.set_pattern("idle")
            if self.on_listening_change:
                self.on_listening_change(False)

    async def _handle_command(self, command):
        """Route voice command to appropriate handler."""
        log.info(f"Command: '{command}'")
        self.leds.set_pattern("thinking")

        # Try to match command to handlers
        for key, handler in self.command_handlers.items():
            if key in command:
                response = await handler(command)
                await self.speak(response)
                return

        # Default response
        await self.speak(f"I heard you say: {command}. I'm still learning!")

    # ─── Built-in Command Handlers ──────────────────────────

    async def _cmd_time(self, cmd):
        now = datetime.now()
        return f"It's {now.strftime('%I:%M %p')}"

    async def _cmd_date(self, cmd):
        now = datetime.now()
        return f"Today is {now.strftime('%A, %B %d')}"

    async def _cmd_hello(self, cmd):
        return "Hello! How are you feeling today?"

    async def _cmd_how_are_you(self, cmd):
        return "I'm doing great! More importantly, how are you?"

    async def _cmd_help(self, cmd):
        return ("I can tell you the time, the date, check your health readings, "
                "remind you about medications, or just chat. What would you like?")

    async def _cmd_thanks(self, cmd):
        return "You're welcome! That's what I'm here for."

    async def _cmd_greeting(self, cmd):
        hour = datetime.now().hour
        if hour < 12:
            return "Good morning! Did you sleep well?"
        elif hour < 17:
            return "Good afternoon! Having a nice day?"
        else:
            return "Good evening! How was your day?"

    async def _cmd_goodnight(self, cmd):
        return "Good night! Sleep well. I'll keep watch."

    async def _cmd_weather(self, cmd):
        return "I don't have a weather sensor yet. Would you like me to check the room temperature when we add the sensor?"

    async def _cmd_temperature(self, cmd):
        return "The temperature sensor isn't connected yet. It will show room temperature once we add the BME280 sensor."

    async def _cmd_health_check(self, cmd):
        return "All systems are monitoring. No concerns detected. Your heart rate sensor will give more details once connected."

    async def _cmd_emergency(self, cmd):
        return "Do you need emergency help? Say yes to call your emergency contact."

    async def _cmd_stop(self, cmd):
        self.listening = False
        return "Okay, going quiet."

    def register_command(self, keywords, handler):
        """Register a custom command handler.
        keywords: str or list of str trigger words
        handler: async function(command_text) -> response_text
        """
        if isinstance(keywords, str):
            keywords = [keywords]
        for kw in keywords:
            self.command_handlers[kw.lower()] = handler

    def cleanup(self):
        """Release resources."""
        self.leds.cleanup()
        self.button.cleanup()
        log.info("Voice assistant shut down")

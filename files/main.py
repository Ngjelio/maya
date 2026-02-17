#!/usr/bin/env python3
"""
🏠 Maya — Main Application
=================================================
Hardware: Raspberry Pi 4 + Waveshare 3.5" LCD (B) + ReSpeaker 2-Mic HAT

Orchestrates all subsystems:
  - Display (pygame → framebuffer → SPI LCD)
  - Voice (ReSpeaker mics → Vosk STT → espeak-ng TTS → speaker)
  - Sensors (I2C bus → auto-detect → live dashboard)
  - Alerts (fall detection, inactivity, medication reminders)

Usage:
  python3 main.py              # Live mode (hardware required)
  python3 main.py --demo       # Demo mode (simulated sensors, windowed)
  python3 main.py --no-voice   # Disable voice subsystem
  python3 main.py --no-display # Headless mode (voice + sensors only)
"""

import sys
import signal
import logging
import asyncio
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import CONFIG, load_config
from modules.display import DisplayManager
from modules.voice import VoiceAssistant
from modules.sensors import SensorHub, DemoSensors
from modules.alerts import AlertSystem

# ─── Parse CLI flags ────────────────────────────────────────
DEMO_MODE = "--demo" in sys.argv
NO_VOICE = "--no-voice" in sys.argv
NO_DISPLAY = "--no-display" in sys.argv

# ─── Logging ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG if "--debug" in sys.argv else logging.INFO,
    format="%(asctime)s [%(name)-12s] %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("Main")


class Maya:
    """Main application orchestrator."""

    def __init__(self):
        load_config()

        # Initialize subsystems
        self.display = DisplayManager(CONFIG["display"], demo=DEMO_MODE)
        self.voice = VoiceAssistant(CONFIG["voice"], CONFIG["audio"])
        self.sensors = SensorHub(CONFIG["sensors"])
        self.alerts = AlertSystem(CONFIG["alerts"], CONFIG["general"]["data_dir"])

        self._tasks = []
        self._running = True

    async def start(self):
        """Initialize and run all subsystems."""
        log.info("=" * 52)
        log.info("  🏠 Maya")
        log.info(f"  Mode: {'DEMO' if DEMO_MODE else 'LIVE'}")
        log.info(f"  Display: {'OFF' if NO_DISPLAY else 'ON'}")
        log.info(f"  Voice: {'OFF' if NO_VOICE else 'ON'}")
        log.info("=" * 52)

        # ─── Display ────────────────────────────────────────
        if not NO_DISPLAY:
            if not self.display.init():
                log.error("Display failed to init. Use --demo or --no-display")
                if not DEMO_MODE:
                    return
            self.display.set_message("Starting up...")

        # ─── Sensors ────────────────────────────────────────
        self.sensors.init()

        if DEMO_MODE:
            demo = DemoSensors(self.sensors)
            demo.register_all()
        else:
            # Register sensors that might be connected
            self.sensors.register("MPU6050", i2c_addr=0x68, interval=0.1)
            self.sensors.register("MAX30102", i2c_addr=0x57, interval=1.0)
            self.sensors.register("BME280", i2c_addr=0x76, interval=10.0)
            self.sensors.register("MLX90614", i2c_addr=0x5A, interval=5.0)

            # I2C scan
            found = await self.sensors.scan_i2c()
            if found:
                log.info(f"I2C devices found: {found}")
            else:
                log.info("No I2C sensors detected (add them later)")

        # Wire sensor updates to display
        if not NO_DISPLAY:
            async def on_sensor_update(name, status, value):
                self.display.update_sensor(name, status, value)
            self.sensors.on_update(on_sensor_update)

        sensor_tasks = await self.sensors.start_all()
        self._tasks.extend(sensor_tasks)

        # ─── Alerts ─────────────────────────────────────────
        if not NO_DISPLAY:
            async def on_visual_alert(alert_type, message):
                self.display.trigger_alert(message)
            self.alerts.on_alert_visual = on_visual_alert

        self._tasks.append(
            asyncio.create_task(self.alerts.check_inactivity())
        )
        self._tasks.append(
            asyncio.create_task(self.alerts.check_medication_reminders())
        )

        # ─── Voice ──────────────────────────────────────────
        if not NO_VOICE:
            await self.voice.setup()

            # Wire voice to display
            if not NO_DISPLAY:
                def on_listen_change(active):
                    self.display.set_voice_active(active)
                    if active:
                        self.display.set_mood("I'm listening...")
                    else:
                        self.display.set_mood("Hello!")

                def on_speech(text):
                    self.display.set_message(f"Heard: {text}")

                def on_result(text):
                    self.display.set_message(text)

                self.voice.on_listening_change = on_listen_change
                self.voice.on_speech_text = on_speech
                self.voice.on_command_result = on_result

            # Wire voice alerts
            self.alerts.on_alert_voice = self.voice.speak

            # Add voice commands that read sensor data
            async def cmd_readings(cmd):
                readings = self.sensors.get_all_readings()
                parts = []
                for name, data in readings.items():
                    if data["status"] == "connected":
                        parts.append(f"{name}: {data['value']}")
                if parts:
                    return "Your current readings are: " + ", ".join(parts)
                return "No sensors are connected yet."

            self.voice.register_command(
                ["readings", "sensors", "vitals", "status"],
                cmd_readings
            )

            self._tasks.append(
                asyncio.create_task(self.voice.listen_continuous())
            )

        # ─── Startup complete ───────────────────────────────
        if not NO_DISPLAY:
            self.display.set_message(
                f"Ready! {'Press button or say \"Hey Maya\"' if not NO_VOICE else 'Monitoring...'}"
            )

        log.info("All systems started ✓")

        # ─── Main render loop ───────────────────────────────
        if not NO_DISPLAY:
            await self._render_loop()
        else:
            # Headless mode — just keep running
            while self._running:
                await asyncio.sleep(0.1)

    async def _render_loop(self):
        """Main display render loop at configured FPS."""
        while self._running and self.display.running:
            self.display.render_frame()
            await asyncio.sleep(1.0 / self.display.fps)

    async def stop(self):
        """Graceful shutdown."""
        log.info("Shutting down...")
        self._running = False

        for task in self._tasks:
            task.cancel()

        self.voice.cleanup()
        self.sensors.cleanup()
        self.display.cleanup()

        log.info("Goodbye! 👋")


# ─── Entry Point ────────────────────────────────────────────

def print_banner():
    mode = "DEMO" if DEMO_MODE else "LIVE"
    print(f"""
    ╔══════════════════════════════════════════════╗
    ║   🏠 Maya v0.2         ║
    ║   RPi 4 + 3.5" LCD (B) + ReSpeaker 2-Mic   ║
    ╠══════════════════════════════════════════════╣
    ║   Mode: {mode:<37s}║
    ║   --demo       Simulated sensors + window   ║
    ║   --no-voice   Disable microphone/speaker   ║
    ║   --no-display Headless mode                ║
    ║   --debug      Verbose logging              ║
    ╚══════════════════════════════════════════════╝
    """)


async def main():
    print_banner()
    app = Maya()

    # Handle signals
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(app.stop()))
        except NotImplementedError:
            pass  # Windows doesn't support add_signal_handler

    try:
        await app.start()
    except KeyboardInterrupt:
        await app.stop()
    except Exception as e:
        log.error(f"Fatal error: {e}", exc_info=True)
        await app.stop()


if __name__ == "__main__":
    asyncio.run(main())

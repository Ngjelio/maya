"""
Sensor Hub — Auto-detecting I2C/GPIO Sensor Manager
====================================================
Manages all connected sensors with plug-and-play detection.
When a new I2C sensor is connected, it's automatically detected
and its data flows to the display and alert system.

Supported sensors (add as you buy them):
  - MPU6050 (0x68): Accelerometer/Gyro — fall detection
  - MAX30102 (0x57): Pulse oximeter — heart rate + SpO2
  - BME280 (0x76): Environmental — temperature + humidity + pressure
  - MLX90614 (0x5A): IR thermometer — body temperature
  - BH1750 (0x23): Light sensor — ambient light level
"""

import time
import logging
import asyncio
from datetime import datetime

log = logging.getLogger("SensorHub")


class SensorHub:
    """Central manager for all hardware sensors."""

    def __init__(self, sensor_config):
        self.config = sensor_config
        self.sensors = {}
        self.callbacks = []     # async functions called on sensor update
        self._tasks = []
        self._bus = None

    def init(self):
        """Initialize I2C bus."""
        try:
            import smbus2
            self._bus = smbus2.SMBus(1)
            log.info("I2C bus 1 opened")
        except ImportError:
            log.warning("smbus2 not installed — I2C sensors disabled")
        except Exception as e:
            log.warning(f"I2C bus failed: {e}")

    def on_update(self, callback):
        """Register callback: async callback(name, status, value)"""
        self.callbacks.append(callback)

    async def scan_i2c(self):
        """Scan I2C bus for connected devices."""
        if not self._bus:
            return {}

        found = {}
        known_addrs = {
            0x68: "MPU6050",
            0x57: "MAX30102",
            0x76: "BME280",
            0x77: "BME280-alt",
            0x5A: "MLX90614",
            0x23: "BH1750",
        }

        for addr in range(0x03, 0x78):
            try:
                self._bus.read_byte(addr)
                name = known_addrs.get(addr, f"Unknown-0x{addr:02x}")
                found[addr] = name
                log.info(f"I2C device found: {name} at 0x{addr:02x}")
            except Exception:
                pass

        return found

    def register(self, name, read_fn=None, interval=1.0, i2c_addr=None):
        """Register a sensor for polling."""
        self.sensors[name] = {
            "name": name,
            "status": "pending",
            "value": "—",
            "read_fn": read_fn,
            "interval": interval,
            "i2c_addr": i2c_addr,
            "last_read": 0,
            "error_count": 0,
        }
        log.info(f"Registered sensor: {name}" +
                 (f" at I2C 0x{i2c_addr:02x}" if i2c_addr else ""))

    async def probe(self, name):
        """Check if a sensor is connected."""
        sensor = self.sensors.get(name)
        if not sensor:
            return False

        if sensor["i2c_addr"] and self._bus:
            try:
                self._bus.read_byte(sensor["i2c_addr"])
                sensor["status"] = "connected"
                log.info(f"{name}: connected at 0x{sensor['i2c_addr']:02x}")
                return True
            except Exception:
                sensor["status"] = "offline"
                return False

        if sensor["read_fn"]:
            try:
                val = await sensor["read_fn"]()
                sensor["status"] = "connected"
                sensor["value"] = str(val)
                return True
            except Exception:
                sensor["status"] = "offline"
                return False

        return False

    async def poll_sensor(self, name):
        """Continuously read a sensor at its interval."""
        sensor = self.sensors[name]
        while True:
            if sensor["status"] == "connected" and sensor["read_fn"]:
                try:
                    val = await sensor["read_fn"]()
                    sensor["value"] = str(val)
                    sensor["error_count"] = 0
                    for cb in self.callbacks:
                        try:
                            await cb(name, sensor["status"], sensor["value"])
                        except Exception as e:
                            log.error(f"Callback error: {e}")
                except Exception as e:
                    sensor["error_count"] += 1
                    if sensor["error_count"] > 5:
                        sensor["status"] = "offline"
                        sensor["value"] = "ERR"
                        log.error(f"{name}: too many errors, marking offline")
                    else:
                        log.debug(f"{name} read error: {e}")

            elif sensor["status"] == "offline":
                # Periodically retry offline sensors
                await self.probe(name)

            await asyncio.sleep(sensor["interval"])

    async def start_all(self):
        """Probe all sensors and start polling connected ones."""
        for name in list(self.sensors.keys()):
            await self.probe(name)

        # Notify display of initial states
        for name, sensor in self.sensors.items():
            for cb in self.callbacks:
                try:
                    await cb(name, sensor["status"], sensor["value"])
                except Exception:
                    pass

        # Start polling tasks
        tasks = []
        for name, sensor in self.sensors.items():
            if sensor["read_fn"]:
                task = asyncio.create_task(self.poll_sensor(name))
                tasks.append(task)
                log.info(f"Polling {name} every {sensor['interval']}s")

        self._tasks = tasks
        return tasks

    def get_reading(self, name):
        """Get latest reading for a sensor."""
        sensor = self.sensors.get(name)
        if sensor:
            return sensor["value"]
        return None

    def get_status(self, name):
        """Get sensor status."""
        sensor = self.sensors.get(name)
        if sensor:
            return sensor["status"]
        return "unknown"

    def get_all_readings(self):
        """Get dict of all sensor readings."""
        return {
            name: {"status": s["status"], "value": s["value"]}
            for name, s in self.sensors.items()
        }

    def cleanup(self):
        """Release I2C bus and cancel tasks."""
        for task in self._tasks:
            task.cancel()
        if self._bus:
            self._bus.close()
        log.info("Sensor hub shut down")


# ═══════════════════════════════════════════════════════════════
#  Demo / Simulated Sensors
# ═══════════════════════════════════════════════════════════════

class DemoSensors:
    """Generate realistic fake sensor data for testing."""

    def __init__(self, hub):
        self.hub = hub
        self._hr = 72
        self._temp = 36.5
        self._room = 21.5
        self._hum = 52

    def register_all(self):
        """Register all demo sensors."""
        import random

        async def fake_heart_rate():
            self._hr += random.uniform(-2, 2)
            self._hr = max(58, min(95, self._hr))
            return f"{int(self._hr)} bpm"

        async def fake_body_temp():
            self._temp += random.uniform(-0.05, 0.05)
            self._temp = max(36.0, min(37.2, self._temp))
            return f"{self._temp:.1f}°C"

        async def fake_room():
            self._room += random.uniform(-0.1, 0.1)
            return f"{self._room:.1f}°C {int(self._hum)}%"

        async def fake_motion():
            return "Active" if random.random() > 0.3 else "Still"

        self.hub.register("MAX30102", read_fn=fake_heart_rate, interval=2.0)
        self.hub.register("MLX90614", read_fn=fake_body_temp, interval=5.0)
        self.hub.register("BME280", read_fn=fake_room, interval=10.0)
        self.hub.register("MPU6050", read_fn=fake_motion, interval=1.0)

        # Set all as "connected" in demo mode
        for name in self.hub.sensors:
            self.hub.sensors[name]["status"] = "connected"

        log.info("Demo sensors registered (4 simulated)")

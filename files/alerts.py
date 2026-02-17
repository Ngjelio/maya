"""
Alert System — Emergency and Wellness Notifications
====================================================
Manages fall detection alerts, inactivity warnings,
medication reminders, and health anomaly detection.
"""

import json
import logging
import asyncio
from datetime import datetime
from pathlib import Path

log = logging.getLogger("Alerts")


class AlertSystem:
    """Handles all alert types with cooldown, logging, and notification."""

    def __init__(self, config, data_dir):
        self.config = config
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self._cooldowns = {}
        self.last_motion = datetime.now()

        # Callbacks
        self.on_alert_visual = None   # async (type, msg) -> None
        self.on_alert_voice = None    # async (msg) -> None

    async def trigger(self, alert_type, message, severity="warning"):
        """
        Trigger an alert.
        severity: 'info', 'warning', 'critical'
        """
        now = datetime.now()
        cooldown = self.config.get("fall_cooldown_seconds", 30)

        # Cooldown check
        if alert_type in self._cooldowns:
            elapsed = (now - self._cooldowns[alert_type]).total_seconds()
            if elapsed < cooldown:
                return
        self._cooldowns[alert_type] = now

        log.warning(f"ALERT [{severity}] {alert_type}: {message}")

        # Log to file
        self._log_alert(alert_type, message, severity)

        # Visual alert on display
        if self.on_alert_visual:
            await self.on_alert_visual(alert_type, message)

        # Voice alert for critical
        if severity == "critical" and self.on_alert_voice:
            await self.on_alert_voice(f"Alert! {message}")

    def _log_alert(self, alert_type, message, severity):
        """Persist alert to JSONL log file."""
        log_file = self.data_dir / "alerts.jsonl"
        entry = {
            "timestamp": datetime.now().isoformat(),
            "type": alert_type,
            "message": message,
            "severity": severity,
        }
        with open(log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")

    async def check_inactivity(self):
        """Periodic check for prolonged inactivity."""
        threshold = self.config.get("inactivity_alert_hours", 4)
        while True:
            hours = (datetime.now() - self.last_motion).total_seconds() / 3600
            if hours > threshold:
                await self.trigger(
                    "inactivity",
                    f"No movement for {hours:.1f} hours",
                    severity="warning"
                )
            await asyncio.sleep(300)

    def update_motion(self):
        """Called when any motion is detected."""
        self.last_motion = datetime.now()

    async def check_medication_reminders(self):
        """Check medication schedule and remind."""
        reminders = self.config.get("medication_reminders", [])
        if not reminders:
            return

        while True:
            now = datetime.now()
            current_time = now.strftime("%H:%M")

            for med in reminders:
                if current_time in med.get("times", []):
                    await self.trigger(
                        "medication",
                        f"Time to take {med['name']}",
                        severity="info"
                    )

            await asyncio.sleep(60)

    def get_recent_alerts(self, count=10):
        """Get last N alerts from log."""
        log_file = self.data_dir / "alerts.jsonl"
        if not log_file.exists():
            return []

        alerts = []
        with open(log_file) as f:
            for line in f:
                try:
                    alerts.append(json.loads(line.strip()))
                except json.JSONDecodeError:
                    pass

        return alerts[-count:]

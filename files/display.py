"""
Display Manager — Pygame Framebuffer Renderer
==============================================
Renders the Maya UI directly on the Waveshare 3.5" LCD (B)
via the Linux framebuffer (/dev/fb0 or /dev/fb1).

The LCD driver (LCD-show/LCD35B-show) maps the SPI display to a
framebuffer device. Pygame renders to it directly — no X server needed.

Screen layout (480×320):
┌──────────────────────────────────────────────┐
│  ⏰ 14:32       Tue, Feb 17      🟢 All OK  │  <- header (40px)
├──────────────────────┬───────────────────────┤
│                      │                       │
│    😊 Maya      │   🎤 Voice            │  <- main (220px)
│    face / animation  │   status + waveform   │
│                      │                       │
├──────────────────────┴───────────────────────┤
│ 🟢MIC  🟢LCD  🟡MPU  🟡MAX  🟡BME          │  <- sensor bar (40px)
├──────────────────────────────────────────────┤
│  💬 Hello! How are you feeling today?        │  <- message bar (20px)
└──────────────────────────────────────────────┘
"""

import os
import sys
import time
import math
import logging
import asyncio
from datetime import datetime

log = logging.getLogger("Display")

# ─── Color Palette ──────────────────────────────────────────
COLORS = {
    "bg":           (26, 26, 46),      # dark navy
    "surface":      (22, 33, 62),      # card background
    "card":         (15, 52, 96),      # darker card
    "accent":       (233, 69, 96),     # coral red (alerts)
    "green":        (78, 204, 163),    # healthy green
    "yellow":       (255, 211, 105),   # warning
    "text":         (234, 234, 234),   # primary text
    "text_dim":     (136, 153, 170),   # secondary text
    "white":        (255, 255, 255),
    "black":        (0, 0, 0),
}


class DisplayManager:
    """
    Renders the maya dashboard on the 3.5" LCD using pygame.
    Designed for framebuffer rendering (no X server required).
    """

    def __init__(self, config, demo=False):
        self.config = config
        self.demo = demo
        self.width = config["width"]    # 480
        self.height = config["height"]  # 320
        self.fps = config.get("fps", 30)
        self.running = False
        self.screen = None
        self.fonts = {}
        self.clock = None

        # State
        self.sensor_data = {}
        self.voice_active = False
        self.voice_text = "Tap button to talk"
        self.maya_mood = "Hello! 👋"
        self.alert_active = False
        self.alert_message = ""
        self.message_text = "Starting up..."
        self.last_activity = time.time()

        # Animation state
        self.blink_timer = 0
        self.blink_state = False
        self.wave_offset = 0
        self.mood_index = 0
        self.mood_timer = 0
        self.moods = [
            "Hello!", "How are you?", "Need anything?",
            "I'm here for you", "Stay hydrated!",
            "Time for a walk?", "Feeling good?",
        ]

    def init(self):
        """Initialize pygame and the display."""
        # Set framebuffer device before pygame init
        if not self.demo:
            # Try fb1 first (typical for SPI LCD), fallback to fb0
            for fb in ["/dev/fb1", "/dev/fb0"]:
                if os.path.exists(fb):
                    os.environ["SDL_FBDEV"] = fb
                    break
            os.environ["SDL_VIDEODRIVER"] = "fbcon"
            os.environ.setdefault("SDL_NOMOUSE", "1")

        try:
            import pygame
            self.pygame = pygame
            pygame.init()

            if self.demo:
                self.screen = pygame.display.set_mode(
                    (self.width, self.height)
                )
                pygame.display.set_caption("Maya — Demo")
            else:
                self.screen = pygame.display.set_mode(
                    (self.width, self.height), pygame.FULLSCREEN
                )
                pygame.mouse.set_visible(False)

            self.clock = pygame.time.Clock()

            # Load fonts
            pygame.font.init()
            font_path = None
            for path in [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
                "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            ]:
                if os.path.exists(path):
                    font_path = path
                    break

            if font_path:
                self.fonts["large"] = pygame.font.Font(font_path, 28)
                self.fonts["medium"] = pygame.font.Font(font_path, 16)
                self.fonts["small"] = pygame.font.Font(font_path, 12)
                self.fonts["tiny"] = pygame.font.Font(font_path, 10)
                bold_path = font_path.replace("Sans.", "Sans-Bold.").replace("Regular", "Bold")
                if os.path.exists(bold_path):
                    self.fonts["large_bold"] = pygame.font.Font(bold_path, 28)
                    self.fonts["medium_bold"] = pygame.font.Font(bold_path, 16)
                else:
                    self.fonts["large_bold"] = self.fonts["large"]
                    self.fonts["medium_bold"] = self.fonts["medium"]
            else:
                # Fallback to pygame default font
                self.fonts["large"] = pygame.font.SysFont(None, 32)
                self.fonts["large_bold"] = pygame.font.SysFont(None, 32, bold=True)
                self.fonts["medium"] = pygame.font.SysFont(None, 18)
                self.fonts["medium_bold"] = pygame.font.SysFont(None, 18, bold=True)
                self.fonts["small"] = pygame.font.SysFont(None, 14)
                self.fonts["tiny"] = pygame.font.SysFont(None, 11)

            self.running = True
            log.info(f"Display initialized: {self.width}x{self.height}")
            return True

        except Exception as e:
            log.error(f"Display init failed: {e}")
            log.info("Run with --demo flag to test without hardware")
            return False

    def update_sensor(self, name, status, value):
        """Update sensor data for display."""
        self.sensor_data[name] = {"status": status, "value": value}

    def set_voice_active(self, active, text=None):
        """Update voice interaction state."""
        self.voice_active = active
        if text:
            self.voice_text = text
        self.last_activity = time.time()

    def set_mood(self, mood_text):
        """Set maya mood message."""
        self.maya_mood = mood_text

    def set_message(self, text):
        """Set bottom message bar text."""
        self.message_text = text
        self.last_activity = time.time()

    def trigger_alert(self, message):
        """Activate alert overlay."""
        self.alert_active = True
        self.alert_message = message
        self.last_activity = time.time()

    def dismiss_alert(self):
        """Dismiss alert overlay."""
        self.alert_active = False

    def render_frame(self):
        """Render one frame of the UI."""
        if not self.running or not self.screen:
            return

        pg = self.pygame
        screen = self.screen
        dt = self.clock.tick(self.fps) / 1000.0

        # Handle pygame events
        for event in pg.event.get():
            if event.type == pg.QUIT:
                self.running = False
                return
            elif event.type == pg.KEYDOWN:
                if event.key == pg.K_ESCAPE:
                    self.running = False
                    return
                elif event.key == pg.K_a:
                    self.trigger_alert("FALL DETECTED")
                elif event.key == pg.K_d:
                    self.dismiss_alert()
            elif event.type == pg.MOUSEBUTTONDOWN:
                # Touch on right half = voice toggle
                x, y = event.pos
                if x > self.width // 2 and 40 < y < 260:
                    self.voice_active = not self.voice_active
                    self.last_activity = time.time()

        # Update animations
        self.blink_timer += dt
        if self.blink_timer > 4.0:
            self.blink_timer = 0
            self.blink_state = True
        elif self.blink_timer > 0.15:
            self.blink_state = False

        self.wave_offset += dt * 5
        self.mood_timer += dt
        if self.mood_timer > 8.0:
            self.mood_timer = 0
            self.mood_index = (self.mood_index + 1) % len(self.moods)
            if not self.voice_active:
                self.maya_mood = self.moods[self.mood_index]

        # ─── Draw ───────────────────────────────────────────
        screen.fill(COLORS["bg"])

        # Ambient glow effects
        self._draw_glow(screen, 60, 60, 120, COLORS["accent"], 40)
        self._draw_glow(screen, 420, 280, 150, COLORS["green"], 30)

        # Header
        self._draw_header(screen)

        # Main panels
        self._draw_maya_panel(screen, dt)
        self._draw_voice_panel(screen, dt)

        # Sensor bar
        self._draw_sensor_bar(screen)

        # Message bar
        self._draw_message_bar(screen)

        # Alert overlay (on top of everything)
        if self.alert_active:
            self._draw_alert_overlay(screen, dt)

        pg.display.flip()

    def _draw_glow(self, screen, cx, cy, radius, color, alpha):
        """Draw a soft ambient glow circle."""
        glow = self.pygame.Surface((radius * 2, radius * 2), self.pygame.SRCALPHA)
        for r in range(radius, 0, -2):
            a = int(alpha * (r / radius))
            self.pygame.draw.circle(
                glow, (*color[:3], a), (radius, radius), r
            )
        screen.blit(glow, (cx - radius, cy - radius))

    def _draw_rounded_rect(self, screen, rect, color, radius=12):
        """Draw a rounded rectangle."""
        pg = self.pygame
        x, y, w, h = rect
        pg.draw.rect(screen, color, (x + radius, y, w - 2*radius, h))
        pg.draw.rect(screen, color, (x, y + radius, w, h - 2*radius))
        pg.draw.circle(screen, color, (x + radius, y + radius), radius)
        pg.draw.circle(screen, color, (x + w - radius, y + radius), radius)
        pg.draw.circle(screen, color, (x + radius, y + h - radius), radius)
        pg.draw.circle(screen, color, (x + w - radius, y + h - radius), radius)

    def _draw_header(self, screen):
        """Draw the top header bar with time and status."""
        now = datetime.now()
        time_str = now.strftime("%H:%M")
        date_str = now.strftime("%a, %b %d")

        # Time
        time_surf = self.fonts["large_bold"].render(time_str, True, COLORS["white"])
        screen.blit(time_surf, (12, 6))

        # Date
        date_surf = self.fonts["small"].render(date_str, True, COLORS["text_dim"])
        screen.blit(date_surf, (90, 16))

        # Status badge
        badge_x = self.width - 110
        self._draw_rounded_rect(screen, (badge_x, 8, 100, 24), COLORS["surface"], 12)
        # Green dot
        dot_pulse = abs(math.sin(time.time() * 2)) * 0.3 + 0.7
        dot_color = tuple(int(c * dot_pulse) for c in COLORS["green"])
        self.pygame.draw.circle(screen, dot_color, (badge_x + 14, 20), 4)
        # Status text
        status_surf = self.fonts["small"].render("All OK", True, COLORS["green"])
        screen.blit(status_surf, (badge_x + 24, 11))

        # Separator line
        self.pygame.draw.line(
            screen, (*COLORS["surface"][:3],),
            (8, 38), (self.width - 8, 38), 1
        )

    def _draw_maya_panel(self, screen, dt):
        """Draw the maya face panel on the left."""
        pg = self.pygame
        panel_rect = (8, 44, 228, 196)
        self._draw_rounded_rect(screen, panel_rect, COLORS["surface"], 14)

        # Top accent line
        pg.draw.line(screen, COLORS["green"], (60, 44), (180, 44), 2)

        cx, cy = 122, 120  # face center

        # Eyes
        eye_y = cy - 12
        eye_h = 16 if not self.blink_state else 2
        eye_y_offset = 0 if not self.blink_state else 7

        # Left eye
        pg.draw.ellipse(screen, COLORS["green"],
                        (cx - 28, eye_y + eye_y_offset, 16, eye_h))
        if not self.blink_state:
            pg.draw.circle(screen, COLORS["white"], (cx - 22, eye_y + 4), 4)

        # Right eye
        pg.draw.ellipse(screen, COLORS["green"],
                        (cx + 12, eye_y + eye_y_offset, 16, eye_h))
        if not self.blink_state:
            pg.draw.circle(screen, COLORS["white"], (cx + 18, eye_y + 4), 4)

        # Mouth (smile)
        if self.voice_active:
            # Talking animation
            mouth_h = int(6 + abs(math.sin(time.time() * 8)) * 8)
            pg.draw.ellipse(screen, COLORS["green"],
                            (cx - 10, cy + 12, 20, mouth_h), 2)
        else:
            pg.draw.arc(screen, COLORS["green"],
                        (cx - 12, cy + 5, 24, 16),
                        3.14, 2 * 3.14, 2)

        # Label
        label = self.fonts["tiny"].render("MAYA", True, COLORS["text_dim"])
        label_rect = label.get_rect(centerx=cx, y=168)
        screen.blit(label, label_rect)

        # Mood text
        mood = self.fonts["small"].render(self.maya_mood, True, COLORS["green"])
        mood_rect = mood.get_rect(centerx=cx, y=184)
        screen.blit(mood, mood_rect)

    def _draw_voice_panel(self, screen, dt):
        """Draw the voice interaction panel on the right."""
        pg = self.pygame
        panel_rect = (244, 44, 228, 196)
        border_color = COLORS["accent"] if self.voice_active else COLORS["surface"]
        self._draw_rounded_rect(screen, panel_rect, COLORS["surface"], 14)

        # Top accent line
        pg.draw.line(screen, COLORS["accent"], (296, 44), (416, 44), 2)

        cx, cy = 358, 110  # center

        # Mic icon circle
        mic_radius = 22
        pg.draw.circle(screen, COLORS["card"], (cx, cy), mic_radius)
        pg.draw.circle(screen, COLORS["accent"], (cx, cy), mic_radius, 2)

        # Mic shape
        pg.draw.rect(screen, COLORS["accent"], (cx-4, cy-12, 8, 16), border_radius=4)
        pg.draw.arc(screen, COLORS["accent"], (cx-8, cy-4, 16, 16), 3.14, 0, 2)
        pg.draw.line(screen, COLORS["accent"], (cx, cy+10), (cx, cy+14), 2)
        pg.draw.line(screen, COLORS["accent"], (cx-4, cy+14), (cx+4, cy+14), 2)

        # Pulse rings when listening
        if self.voice_active:
            for i in range(3):
                radius = mic_radius + 8 + i * 10
                alpha = max(0, 180 - i * 60 - int(self.wave_offset * 30) % 60)
                ring_surf = pg.Surface((radius*2, radius*2), pg.SRCALPHA)
                pg.draw.circle(ring_surf, (*COLORS["accent"], alpha),
                               (radius, radius), radius, 2)
                screen.blit(ring_surf, (cx - radius, cy - radius))

        # Waveform bars
        if self.voice_active:
            bar_y = cy + 36
            bar_width = 3
            bar_gap = 5
            num_bars = 9
            start_x = cx - (num_bars * (bar_width + bar_gap)) // 2
            for i in range(num_bars):
                h = int(4 + abs(math.sin(self.wave_offset + i * 0.7)) * 14)
                bx = start_x + i * (bar_width + bar_gap)
                pg.draw.rect(screen, COLORS["accent"],
                             (bx, bar_y - h//2, bar_width, h), border_radius=1)

        # Label
        label = self.fonts["tiny"].render("VOICE", True, COLORS["text_dim"])
        label_rect = label.get_rect(centerx=cx, y=168)
        screen.blit(label, label_rect)

        # Status text
        status_color = COLORS["accent"] if self.voice_active else COLORS["text_dim"]
        status_text = "Listening..." if self.voice_active else self.voice_text
        status = self.fonts["small"].render(status_text, True, status_color)
        status_rect = status.get_rect(centerx=cx, y=184)
        screen.blit(status, status_rect)

    def _draw_sensor_bar(self, screen):
        """Draw the bottom sensor status pills."""
        pg = self.pygame
        y = 248
        x = 8

        # Default sensors (always shown)
        default_sensors = [
            ("MIC", "connected", "Ready"),
            ("LCD", "connected", "480x320"),
        ]

        all_sensors = default_sensors + [
            (name, data["status"], data["value"])
            for name, data in self.sensor_data.items()
        ]

        for name, status, value in all_sensors:
            # Pill background
            text = f"{name}: {value}"
            text_surf = self.fonts["tiny"].render(text, True, COLORS["text_dim"])
            pill_w = text_surf.get_width() + 22
            self._draw_rounded_rect(screen, (x, y, pill_w, 20), COLORS["surface"], 10)

            # Status dot
            dot_colors = {
                "connected": COLORS["green"],
                "pending": COLORS["yellow"],
                "offline": COLORS["accent"],
            }
            dot_color = dot_colors.get(status, COLORS["text_dim"])
            pg.draw.circle(screen, dot_color, (x + 10, y + 10), 3)

            # Text
            screen.blit(text_surf, (x + 18, y + 4))

            x += pill_w + 6
            if x > self.width - 50:
                break  # don't overflow

    def _draw_message_bar(self, screen):
        """Draw the bottom message/status bar."""
        y = 275
        msg = self.fonts["small"].render(self.message_text, True, COLORS["text_dim"])
        msg_rect = msg.get_rect(centerx=self.width // 2, y=y)
        screen.blit(msg, msg_rect)

    def _draw_alert_overlay(self, screen, dt):
        """Draw full-screen alert overlay."""
        pg = self.pygame

        # Flashing red background
        flash = abs(math.sin(time.time() * 4))
        alpha = int(200 + flash * 55)
        overlay = pg.Surface((self.width, self.height), pg.SRCALPHA)
        overlay.fill((*COLORS["accent"], min(alpha, 255)))
        screen.blit(overlay, (0, 0))

        # Warning icon
        icon = self.fonts["large_bold"].render("⚠", True, COLORS["white"])
        icon_rect = icon.get_rect(centerx=self.width//2, centery=100)
        screen.blit(icon, icon_rect)

        # Alert text
        alert = self.fonts["large_bold"].render(
            self.alert_message, True, COLORS["white"]
        )
        alert_rect = alert.get_rect(centerx=self.width//2, centery=160)
        screen.blit(alert, alert_rect)

        # Sub text
        sub = self.fonts["medium"].render(
            "Contacting emergency...", True, COLORS["white"]
        )
        sub_rect = sub.get_rect(centerx=self.width//2, centery=200)
        screen.blit(sub, sub_rect)

        # Dismiss instruction
        dismiss = self.fonts["small"].render(
            "Touch screen to dismiss", True, COLORS["white"]
        )
        dismiss_rect = dismiss.get_rect(centerx=self.width//2, centery=280)
        screen.blit(dismiss, dismiss_rect)

    def cleanup(self):
        """Shut down display."""
        self.running = False
        if self.pygame:
            self.pygame.quit()
        log.info("Display shut down")

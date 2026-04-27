"""
notifications.py
────────────────
Alert notification dispatcher for ThreatSense-AI.

Sends real-time notifications when a weapon is confirmed or a high-risk
event is logged.  Currently supports:
  - Email  (SMTP — Gmail App Password or any SMTP relay)

Configuration via environment variables (see .env.example):
  ALERT_EMAIL_ENABLED  true | false
  ALERT_SMTP_HOST      smtp.gmail.com
  ALERT_SMTP_PORT      587
  ALERT_SMTP_USER      your-email@gmail.com
  ALERT_SMTP_PASS      your-app-password
  ALERT_EMAIL_TO       security-team@yourorg.com  (comma-separated for multiple)
"""

from __future__ import annotations

import logging
import os
import smtplib
import threading
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

_log = logging.getLogger("backend.notifications")

IST = timezone(timedelta(hours=5, minutes=30))


def _ist_now() -> str:
    return datetime.now(IST).strftime("%d %b %Y, %I:%M:%S %p IST")


# ── Email notifier ────────────────────────────────────────────────────────────

class EmailNotifier:
    """SMTP email notifier.  Sends alerts in a background thread."""

    def __init__(self) -> None:
        self.enabled  = os.environ.get("ALERT_EMAIL_ENABLED", "false").lower() == "true"
        self.host     = os.environ.get("ALERT_SMTP_HOST", "smtp.gmail.com")
        self.port     = int(os.environ.get("ALERT_SMTP_PORT", "587"))
        self.user     = os.environ.get("ALERT_SMTP_USER", "")
        self.password = os.environ.get("ALERT_SMTP_PASS", "")
        recipients    = os.environ.get("ALERT_EMAIL_TO", "")
        self.to_addrs = [r.strip() for r in recipients.split(",") if r.strip()]

        if self.enabled:
            if not self.user or not self.password:
                _log.warning("[notifications] Email enabled but ALERT_SMTP_USER/PASS not set — disabling")
                self.enabled = False
            elif not self.to_addrs:
                _log.warning("[notifications] Email enabled but ALERT_EMAIL_TO not set — disabling")
                self.enabled = False
            else:
                _log.info("[notifications] Email alerts → %s", self.to_addrs)

    def send_weapon_alert(
        self,
        person_id: str,
        weapon_class: str,
        confidence: float,
        camera_id: str = "CAM-01",
        location: str = "Main Entrance",
    ) -> None:
        """Fire-and-forget: dispatch weapon detection email in a background thread."""
        if not self.enabled:
            return
        threading.Thread(
            target=self._send,
            args=(person_id, weapon_class, confidence, camera_id, location),
            daemon=True,
        ).start()

    def _send(
        self,
        person_id: str,
        weapon_class: str,
        confidence: float,
        camera_id: str,
        location: str,
    ) -> None:
        subject = f"[ThreatSense-AI] WEAPON DETECTED — {weapon_class.upper()} @ {location}"

        html = f"""
        <html><body style="font-family:Arial,sans-serif;background:#0f172a;color:#e2e8f0;padding:20px;">
        <div style="max-width:600px;margin:auto;background:#1e293b;border-radius:8px;
                    border-left:4px solid #ef4444;padding:24px;">
          <h2 style="color:#ef4444;margin:0 0 16px;">⚠ THREAT DETECTED</h2>
          <table style="width:100%;border-collapse:collapse;">
            <tr><td style="padding:8px 0;color:#94a3b8;">Time</td>
                <td style="padding:8px 0;font-weight:bold;">{_ist_now()}</td></tr>
            <tr><td style="padding:8px 0;color:#94a3b8;">Weapon</td>
                <td style="padding:8px 0;color:#ef4444;font-weight:bold;text-transform:uppercase;">{weapon_class}</td></tr>
            <tr><td style="padding:8px 0;color:#94a3b8;">Confidence</td>
                <td style="padding:8px 0;">{confidence*100:.1f}%</td></tr>
            <tr><td style="padding:8px 0;color:#94a3b8;">Person ID</td>
                <td style="padding:8px 0;">{person_id}</td></tr>
            <tr><td style="padding:8px 0;color:#94a3b8;">Camera</td>
                <td style="padding:8px 0;">{camera_id}</td></tr>
            <tr><td style="padding:8px 0;color:#94a3b8;">Location</td>
                <td style="padding:8px 0;">{location}</td></tr>
          </table>
          <p style="margin:20px 0 0;color:#64748b;font-size:12px;">
            ThreatSense-AI Surveillance System — automated alert
          </p>
        </div>
        </body></html>
        """

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = self.user
        msg["To"]      = ", ".join(self.to_addrs)
        msg.attach(MIMEText(html, "html"))

        try:
            with smtplib.SMTP(self.host, self.port, timeout=10) as server:
                server.ehlo()
                server.starttls()
                server.login(self.user, self.password)
                server.sendmail(self.user, self.to_addrs, msg.as_string())
            _log.info("[notifications] Weapon alert email sent to %s", self.to_addrs)
        except Exception as exc:
            _log.error("[notifications] Failed to send email: %s", exc)


# ── Singleton ─────────────────────────────────────────────────────────────────
notifier = EmailNotifier()

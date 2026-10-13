"""Transactional email: SMTP when configured; in development, links are written to the server log instead."""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from ..config import get_settings

log = logging.getLogger("scamshield.mail")


def delivery_mode() -> str:
    """email | server_log (development only) | unavailable."""
    s = get_settings()
    if s.smtp_host and s.smtp_from:
        return "email"
    return "server_log" if s.is_dev else "unavailable"


def _deliver(to: str, subject: str, body: str, purpose: str, link: str) -> None:
    s = get_settings()
    mode = delivery_mode()
    if mode == "email":
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = s.smtp_from
        msg["To"] = to
        msg.set_content(body)
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
            smtp.starttls()
            if s.smtp_user and s.smtp_password:
                smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)
    elif mode == "server_log":
        # Development only: never enabled when SCAMSHIELD_ENV is production.
        log.warning("[DEV ONLY] %s link for %s: %s", purpose, to, link)
    else:
        log.warning("%s email requested but no SMTP server is configured", purpose)


def send_reset_link(to: str, link: str) -> None:
    _deliver(to, "Reset your ScamShield AI password",
             f"Use this link within 30 minutes to reset your password:\n\n{link}\n\nIf you did not request this, ignore this email.",
             "Password reset", link)


def send_verification_link(to: str, link: str) -> None:
    _deliver(to, "Verify your ScamShield AI email",
             f"Confirm this address for your ScamShield AI account (link valid for 48 hours):\n\n{link}\n\nIf you did not create an account, ignore this email.",
             "Email verification", link)


def send_invite(to: str, org_name: str, link: str) -> None:
    _deliver(to, f"You are invited to {org_name} on ScamShield AI",
             f"You have been invited to join {org_name}. Create your account within 7 days:\n\n{link}\n",
             "Invitation", link)

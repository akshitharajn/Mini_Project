"""SMTP-based auth event email notifications."""

from __future__ import annotations

import asyncio
import logging
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage

from backend.app.config import get_settings

logger = logging.getLogger(__name__)


def _is_smtp_configured() -> bool:
    settings = get_settings()
    return bool(
        settings.auth_email_enabled
        and settings.smtp_host
        and settings.smtp_port
        and settings.smtp_username
        and settings.smtp_password
        and settings.smtp_from_email
    )


def _build_event_mail(to_email: str, name: str, event: str) -> EmailMessage:
    settings = get_settings()
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    if event == "signup":
        subject = "Welcome to Study Assistant"
        plain = (
            f"Hi {name},\n\n"
            "Your account was created successfully.\n"
            f"Time: {now_utc}\n\n"
            "You can now start planning your study schedule."
        )
        html = (
            f"<p>Hi {name},</p>"
            "<p>Your account was created successfully.</p>"
            f"<p><strong>Time:</strong> {now_utc}</p>"
            "<p>You can now start planning your study schedule.</p>"
        )
    else:
        subject = "Login Alert - Study Assistant"
        plain = (
            f"Hi {name},\n\n"
            "We detected a login to your account.\n"
            f"Time: {now_utc}\n\n"
            "If this was not you, please reset your password."
        )
        html = (
            f"<p>Hi {name},</p>"
            "<p>We detected a login to your account.</p>"
            f"<p><strong>Time:</strong> {now_utc}</p>"
            "<p>If this was not you, please reset your password.</p>"
        )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
    msg["To"] = to_email
    msg.set_content(plain)
    msg.add_alternative(html, subtype="html")
    return msg


def _send_sync(message: EmailMessage) -> None:
    settings = get_settings()
    if settings.smtp_use_ssl:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20) as server:
            server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(message)
        return

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as server:
        if settings.smtp_starttls:
            server.starttls()
        server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)


async def send_auth_event_email(to_email: str, name: str, event: str) -> bool:
    """Send signup/login email. Returns True on success, False on skip/failure."""
    if not _is_smtp_configured():
        logger.info("Auth email skipped: SMTP is not configured.")
        return False

    message = _build_event_mail(to_email=to_email, name=name, event=event)
    try:
        await asyncio.to_thread(_send_sync, message)
        return True
    except Exception:
        logger.exception("Failed to send %s auth email to %s", event, to_email)
        return False

"""SMTP-based auth event email notifications."""

from __future__ import annotations

import asyncio
import logging
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage

try:
    import resend
except Exception:  # pragma: no cover - optional dependency import guard
    resend = None

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


def _is_resend_configured() -> bool:
    settings = get_settings()
    return bool(
        settings.auth_email_enabled
        and settings.auth_email_provider == "resend"
        and settings.resend_api_key.strip()
        and settings.resend_from_email.strip()
        and resend is not None
    )


def _build_event_mail(to_email: str, name: str, event: str) -> EmailMessage:
    settings = get_settings()
    subject, plain, html = _build_event_content(name=name, event=event)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = _format_sender(settings.smtp_from_name, settings.smtp_from_email)
    msg["To"] = to_email
    msg.set_content(plain)
    msg.add_alternative(html, subtype="html")
    return msg


def _format_sender(sender_name: str, sender_email: str) -> str:
    sender_name = sender_name.strip() if isinstance(sender_name, str) else "Study Assistant"
    sender_email = sender_email.strip()
    if sender_name:
        return f"{sender_name} <{sender_email}>"
    return sender_email


def _build_event_content(name: str, event: str) -> tuple[str, str, str]:
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    if event == "signup":
        subject = "Welcome to Study Assistant!"
        plain = (
            f"Hi {name},\n\n"
            "Welcome to Study Assistant!! Your account was created successfully.\n"
            f"Time: {now_utc}\n\n"
            "You can now start planning your study schedule and quizzes."
        )
        html = (
            f"<p>Hi {name},</p>"
            "<p><strong>Welcome to Study Assistant!!</strong> Your account was created successfully.</p>"
            f"<p><strong>Time:</strong> {now_utc}</p>"
            "<p>You can now start planning your study schedule and quizzes.</p>"
        )
        return subject, plain, html

    subject = "Welcome back to Study Assistant!!"
    plain = (
        f"Hi {name},\n\n"
        "Welcome back!! You have logged in successfully.\n"
        f"Time: {now_utc}\n\n"
        "If this was not you, please reset your password immediately."
    )
    html = (
        f"<p>Hi {name},</p>"
        "<p><strong>Welcome back!!</strong> You have logged in successfully.</p>"
        f"<p><strong>Time:</strong> {now_utc}</p>"
        "<p>If this was not you, please reset your password immediately.</p>"
    )
    return subject, plain, html


def _send_resend_sync(to_email: str, name: str, event: str) -> None:
    settings = get_settings()
    subject, plain, html = _build_event_content(name=name, event=event)
    if resend is None:
        raise RuntimeError("resend package is not installed")

    resend.api_key = settings.resend_api_key.strip()
    resend.Emails.send(
        {
            "from": _format_sender(settings.smtp_from_name, settings.resend_from_email),
            "to": [to_email],
            "subject": subject,
            "text": plain,
            "html": html,
        }
    )


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
    try:
        if _is_resend_configured():
            await asyncio.to_thread(_send_resend_sync, to_email, name, event)
            return True

        if _is_smtp_configured():
            message = _build_event_mail(to_email=to_email, name=name, event=event)
            await asyncio.to_thread(_send_sync, message)
            return True

        logger.info("Auth email skipped: neither Resend nor SMTP is configured.")
        return False
    except Exception:
        logger.exception("Failed to send %s auth email to %s", event, to_email)
        return False

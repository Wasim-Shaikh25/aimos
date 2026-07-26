"""SMTP email sender for verification and password reset.

SMTP credentials come from ``config/saas.yaml`` or ``AIMOS__SAAS__SMTP__*``
environment overrides. When no credentials are configured the email is logged
instead of sent (safe default for local development).
"""

from __future__ import annotations

import smtplib
import structlog
from email.mime.text import MIMEText
from pathlib import Path

from aimos.saas.settings import get_saas_config

log = structlog.get_logger(__name__)


def _render_verification_email(code: str, base_url: str) -> tuple[str, str]:
    subject = "AIMOS verification code"
    text = (
        f"Welcome to AIMOS.\n\nYour verification code is: {code}\n\n"
        f"Enter it in the app or visit {base_url}/verify?code={code}\n\n"
        "If you did not register, ignore this email."
    )
    html = (
        f"<html><body><p>Welcome to AIMOS.</p>"
        f"<p>Your verification code is: <strong>{code}</strong></p>"
        f"<p><a href='{base_url}/verify?code={code}'>Verify</a></p>"
        f"<p>If you did not register, ignore this email.</p></body></html>"
    )
    return text, html


def _render_password_reset_email(code: str, base_url: str) -> tuple[str, str]:
    subject = "AIMOS password reset"
    text = (
        f"You requested a password reset.\n\nYour reset code is: {code}\n\n"
        f"Enter it in the app or visit {base_url}/reset-password?code={code}\n\n"
        "If you did not request this, ignore this email."
    )
    return text, html


def send_email(to: str, subject: str, text_body: str, html_body: str | None = None) -> None:
    """Send an email via SMTP or log it if no SMTP credentials are configured."""
    cfg = get_saas_config()
    smtp = cfg.smtp
    if not smtp.host or not smtp.username:
        log.warning(
            "email_not_sent_no_smtp",
            to=to,
            subject=subject,
            body=text_body[:200],
        )
        return

    msg = MIMEText(html_body or text_body, "html" if html_body else "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = smtp.from_address
    msg["To"] = to

    try:
        with smtplib.SMTP(smtp.host, smtp.port, timeout=30) as server:
            if smtp.use_tls:
                server.starttls()
            if smtp.password:
                server.login(smtp.username, smtp.password)
            server.sendmail(smtp.from_address, [to], msg.as_string())
    except Exception:
        log.exception("smtp_send_failed", to=to)
        raise


def send_verification_email(to: str, code: str, base_url: str = "") -> None:
    """Send an email verification code."""
    cfg = get_saas_config()
    text, html = _render_verification_email(code, base_url or "http://localhost:8000")
    send_email(to, "AIMOS verification code", text, html)
    # Also write a local copy for dev environments with no SMTP.
    _dev_drop(f"verify-{to}", code)


def send_password_reset_email(to: str, code: str, base_url: str = "") -> None:
    """Send a password reset code."""
    text, html = _render_password_reset_email(code, base_url or "http://localhost:8000")
    send_email(to, "AIMOS password reset", text, html)
    _dev_drop(f"reset-{to}", code)


def _dev_drop(prefix: str, code: str) -> None:
    """Write the code to ``state/maildrop`` for local development."""
    drop_dir = Path("state") / "maildrop"
    drop_dir.mkdir(parents=True, exist_ok=True)
    (drop_dir / f"{prefix}.txt").write_text(code, encoding="utf-8")

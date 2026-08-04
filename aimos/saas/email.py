"""SMTP email sender for the admin login OTP (the only email the app sends).

SMTP credentials come from ``config/saas.yaml`` or ``AIMOS__SAAS__SMTP__*``
environment overrides. Brevo's free-tier SMTP relay is the recommended provider
for operators with no existing mail infra — see specs/OPERATIONS.md. When no
credentials are configured the email is not sent (see ``_dev_drop`` below).
"""

from __future__ import annotations

import os
import smtplib
import stat
import structlog
from email.mime.text import MIMEText
from pathlib import Path

from aimos.saas.settings import get_saas_config

log = structlog.get_logger(__name__)


def send_email(to: str, subject: str, text_body: str, html_body: str | None = None) -> None:
    """Send an email via SMTP or log it if no SMTP credentials are configured."""
    cfg = get_saas_config()
    smtp = cfg.smtp
    if not smtp.host or not smtp.username:
        # Never log the body — verification/login/reset emails carry one-time
        # codes, and "secrets are never logged" is a hard rule (audit finding H2).
        log.warning("email_not_sent_no_smtp", to=to, subject=subject)
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


def send_login_code_email(to: str, code: str) -> None:
    """Send a one-time login code (email-based 2FA)."""
    text = f"Your AIMOS login code is: {code}\n\nIt expires in 10 minutes."
    html = f"<html><body><p>Your AIMOS login code is: <strong>{code}</strong></p><p>It expires in 10 minutes.</p></body></html>"
    send_email(to, "AIMOS login code", text, html)
    _dev_drop(f"login-{to}", code)


def _dev_drop(prefix: str, code: str) -> None:
    """Write the code to ``state/maildrop`` — DEV ONLY, opt-in.

    Disabled by default: a one-time code written to a plaintext file defeats the
    second factor (audit finding H2). Set ``AIMOS_DEV_MAILDROP=1`` for local
    development with no SMTP.
    """
    if os.environ.get("AIMOS_DEV_MAILDROP", "").strip().lower() not in ("1", "true", "yes"):
        return
    drop_dir = Path("state") / "maildrop"
    drop_dir.mkdir(parents=True, exist_ok=True)
    path = drop_dir / f"{prefix}.txt"
    path.write_text(code, encoding="utf-8")
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600 — owner only
    except OSError:
        pass

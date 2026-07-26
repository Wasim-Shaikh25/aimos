"""Pluggable SMS sender for phone OTP.

By default the OTP is only logged. Real SMS requires operator-supplied gateway
credentials (Twilio/Vonage) in ``config/saas.yaml``. AIMOS never pays for SMS.
"""

from __future__ import annotations

import base64
import structlog
from abc import ABC, abstractmethod
from pathlib import Path

import httpx

from aimos.saas.settings import get_saas_config

log = structlog.get_logger(__name__)


class SMSSender(ABC):
    @abstractmethod
    def send(self, phone_number: str, message: str) -> None:
        ...


class ConsoleSMSSender(SMSSender):
    """Logs the message; default for local development."""

    def send(self, phone_number: str, message: str) -> None:
        log.info("sms_console", phone=phone_number, message=message)
        _dev_drop(phone_number, message)


class TwilioSMSSender(SMSSender):
    """Send via Twilio REST API using httpx."""

    def __init__(self, account_sid: str, auth_token: str, from_number: str) -> None:
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number
        self.url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"

    def send(self, phone_number: str, message: str) -> None:
        auth = base64.b64encode(
            f"{self.account_sid}:{self.auth_token}".encode()
        ).decode("ascii")
        resp = httpx.post(
            self.url,
            headers={"Authorization": f"Basic {auth}"},
            data={"From": self.from_number, "To": phone_number, "Body": message},
            timeout=30.0,
        )
        resp.raise_for_status()


class VonageSMSSender(SMSSender):
    """Send via Vonage SMS API using httpx."""

    def __init__(self, api_key: str, api_secret: str, from_name: str) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.from_name = from_name

    def send(self, phone_number: str, message: str) -> None:
        resp = httpx.post(
            "https://rest.nexmo.com/sms/json",
            json={
                "api_key": self.api_key,
                "api_secret": self.api_secret,
                "from": self.from_name,
                "to": phone_number,
                "text": message,
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("messages", [{}])[0].get("status") != "0":
            raise RuntimeError(f"Vonage send failed: {data}")


def _dev_drop(phone_number: str, message: str) -> None:
    drop_dir = Path("state") / "smsdrop"
    drop_dir.mkdir(parents=True, exist_ok=True)
    safe = phone_number.replace("+", "").replace("/", "_")
    (drop_dir / f"{safe}.txt").write_text(message, encoding="utf-8")


def get_sms_sender() -> SMSSender:
    """Return the configured SMS sender."""
    cfg = get_saas_config().sms
    if cfg.driver == "twilio" and cfg.twilio.account_sid:
        return TwilioSMSSender(
            cfg.twilio.account_sid,
            cfg.twilio.auth_token,
            cfg.twilio.from_number,
        )
    if cfg.driver == "vonage" and cfg.vonage.api_key:
        return VonageSMSSender(
            cfg.vonage.api_key,
            cfg.vonage.api_secret,
            cfg.vonage.from_name,
        )
    return ConsoleSMSSender()


def send_otp(phone_number: str, code: str) -> None:
    """Send an OTP to a phone number via the configured driver."""
    sender = get_sms_sender()
    sender.send(phone_number, f"Your AIMOS verification code is: {code}")

"""Sending email. One small interface, two ways to deliver.

BEISMART_MAIL=outbox (the default) writes each message to logs/outbox/ so nothing is ever sent by accident
while developing or testing. BEISMART_MAIL=smtp sends for real through any SMTP server (a Gmail app
password, or a transactional email service), set with these environment variables:

    BEISMART_SMTP_HOST, BEISMART_SMTP_PORT (587), BEISMART_SMTP_USER, BEISMART_SMTP_PASSWORD,
    BEISMART_MAIL_FROM (defaults to the user)"""

import os
import re
import smtplib
import time
from email.message import EmailMessage
from email.utils import formataddr
from typing import Optional, Protocol


class Mailer(Protocol):
    def send(self, to: str, subject: str, text: str, html: Optional[str] = None) -> None: ...


class MailError(Exception):
    """The message could not be sent."""


class OutboxMailer:
    """Writes messages to a folder instead of sending them."""

    def __init__(self, folder: str = os.path.join("logs", "outbox")):
        self.folder = folder

    def send(self, to: str, subject: str, text: str, html: Optional[str] = None) -> None:
        os.makedirs(self.folder, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", subject.lower()).strip("-")[:50]
        base = os.path.join(self.folder, f"{time.strftime('%Y%m%d-%H%M%S')}-{slug}")
        n = 0
        while os.path.exists(f"{base}{'' if not n else f'-{n}'}.txt"):
            n += 1
        base = f"{base}{'' if not n else f'-{n}'}"
        with open(base + ".txt", "w", encoding="utf-8") as f:
            f.write(f"To: {to}\nSubject: {subject}\n\n{text}\n")
        if html:
            with open(base + ".html", "w", encoding="utf-8") as f:
                f.write(html)


class SmtpMailer:
    def __init__(self, host: str, port: int, user: str, password: str, sender: str):
        self.host, self.port, self.user, self.password, self.sender = host, port, user, password, sender

    def send(self, to: str, subject: str, text: str, html: Optional[str] = None) -> None:
        msg = EmailMessage()
        msg["From"] = formataddr(("BeiSmart KE", self.sender))
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(text)
        if html:
            msg.add_alternative(html, subtype="html")
        try:
            with smtplib.SMTP(self.host, self.port, timeout=30) as server:
                server.starttls()
                server.login(self.user, self.password)
                server.send_message(msg)
        except (smtplib.SMTPException, OSError) as exc:
            raise MailError(f"Could not send email to {to}: {exc.__class__.__name__}") from exc


def get_mailer() -> Mailer:
    """The mailer chosen by BEISMART_MAIL (outbox unless set to smtp)."""
    if os.environ.get("BEISMART_MAIL", "outbox").lower() == "smtp":
        host = os.environ.get("BEISMART_SMTP_HOST", "")
        user = os.environ.get("BEISMART_SMTP_USER", "")
        password = os.environ.get("BEISMART_SMTP_PASSWORD", "")
        if not (host and user and password):
            raise MailError("BEISMART_MAIL=smtp needs BEISMART_SMTP_HOST, BEISMART_SMTP_USER and BEISMART_SMTP_PASSWORD")
        return SmtpMailer(host, int(os.environ.get("BEISMART_SMTP_PORT", "587")), user, password,
                          os.environ.get("BEISMART_MAIL_FROM", user))
    return OutboxMailer()

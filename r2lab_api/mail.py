import logging
import smtplib
from email.mime.text import MIMEText

from .config import settings

log = logging.getLogger(__name__)


def send_mail(to: str, subject: str, body: str) -> None:
    if settings.mail_mode == "console":
        print(f"\n{'=' * 60}")
        print(f"  To: {to}")
        print(f"  Subject: {subject}")
        print(f"{'=' * 60}")
        print(body)
        print(f"{'=' * 60}\n")
        return

    msg = MIMEText(body, "plain")
    msg["From"] = settings.mail_from
    msg["To"] = to
    msg["Subject"] = subject
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
            smtp.send_message(msg)
        log.info("sent mail to %s: %s", to, subject)
    except Exception:
        log.exception("failed to send mail to %s: %s", to, subject)

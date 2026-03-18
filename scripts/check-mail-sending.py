#!/usr/bin/env python3
"""
Smoke-test: send a short mail to several destinations
using the same send_mail() as the API.

Usage:
    cd /root/r2lab-api
    .venv/bin/python scripts/check-mail-sending.py
"""

import sys
from pathlib import Path

# make sure r2lab_api is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from r2lab_api.config import settings
from r2lab_api.mail import send_mail

DESTINATIONS = [
    "thierry.parmentelat@gmail.com",
    "turletti@gmail.com",
    "thierry.parmentelat@free.fr",
    "thierry.parmentelat@inria.fr",
]

SUBJECT = "check mail from r2labapi"

BODY = """\
This is a routine mail message to check that r2labapi.inria.fr
is capable of sending to a recipient on gmail.com

Sending mails is used to notify users
- of progress in the registration workflow
- of slices that need to be renewed and are about to be cleaned up
"""

print(f"mail_mode={settings.mail_mode}  smtp={settings.smtp_host}:{settings.smtp_port}  from={settings.mail_from}")

for dest in DESTINATIONS:
    print(f"  → {dest} ... ", end="", flush=True)
    try:
        send_mail(to=dest, subject=SUBJECT, body=BODY)
        print("ok")
    except Exception as exc:
        print(f"FAILED: {exc}")

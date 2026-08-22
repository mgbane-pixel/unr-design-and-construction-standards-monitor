#!/usr/bin/env python3
"""
Document Change Monitor
Checks the UNR Design and Construction Standards page for a new document link.
If the link changes, emails a distribution list with the old and new link so
someone can pull both versions and run a comparison manually.
"""

import os
import re
import sys
import json
import smtplib
import requests
import datetime
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ── Config (loaded from environment variables set in GitHub Actions secrets) ──
DOC_URL          = os.environ["DOC_URL"]           # URL of the UNR page to watch
EMAIL_SENDER     = os.environ["EMAIL_SENDER"]      # Gmail address sending the email
EMAIL_PASSWORD   = os.environ["EMAIL_PASSWORD"]    # Gmail App Password (not your real password)
EMAIL_RECIPIENTS = os.environ["EMAIL_RECIPIENTS"]  # Comma-separated list of recipients
DOC_NAME         = os.environ.get("DOC_NAME", "Owner Standards Document")

# Paths
DATA_DIR   = Path("data")
STATE_FILE = DATA_DIR / "state.json"

DATA_DIR.mkdir(exist_ok=True)


# ── Utilities ────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"last_link": None, "last_label": None, "last_checked": None, "last_changed": None}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def check_for_page_change(page_url: str) -> dict:
    """Fetch the UNR standards page and pull out the current doc link + label."""
    r = requests.get(page_url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()

    matches = re.findall(
        r'href="([^"]*box\.com/s/[^"]+)"[^>]*>\s*(?:<strong>)?([^<]{0,120})',
        r.text, re.IGNORECASE
    )
    for href, label in matches:
        if "design and construction standards" in label.lower():
            return {"link": href, "label": label.strip()}

    raise ValueError("Could not find the standards link on the page — UNR may have changed the page layout.")


# ── Email ──────────────────────────────────────────────────────────────────────

def send_alert_email(previous_link: str, current: dict, check_date: str):
    recipients = [r.strip() for r in EMAIL_RECIPIENTS.split(",") if r.strip()]
    subject = f"[Doc Update] {DOC_NAME} — Link Changed"

    body = f"""The UNR Design and Construction Standards page has a new document posted.

Detected: {check_date}

Previous: {previous_link or '(none — first run)'}
Current:  {current['label']}
          {current['link']}

Check the page and grab both versions if you want a comparison:
{DOC_URL}
"""

    msg = MIMEMultipart()
    msg["From"]    = EMAIL_SENDER
    msg["To"]      = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, recipients, msg.as_string())
    print(f"✓ Alert email sent to: {', '.join(recipients)}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    check_date = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n{'='*60}")
    print(f"Document Monitor — {check_date}")
    print(f"Checking: {DOC_URL}")
    print(f"{'='*60}")

    state = load_state()

    print("\n→ Checking page for current document link...")
    try:
        current = check_for_page_change(DOC_URL)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    print(f"  Current: {current['label']} -> {current['link']}")

    previous_link = state.get("last_link")

    if previous_link == current["link"]:
        print("\n✓ No change detected.")
        state["last_checked"] = check_date
        save_state(state)
        return

    if previous_link is None:
        print("  First run — storing baseline. No email sent.")
        state.update({
            "last_link": current["link"],
            "last_label": current["label"],
            "last_checked": check_date,
            "last_changed": check_date,
        })
        save_state(state)
        print("✓ Baseline stored. Future changes will trigger email alerts.")
        return

    print("\n⚠ CHANGE DETECTED")
    send_alert_email(previous_link, current, check_date)

    state.update({
        "last_link": current["link"],
        "last_label": current["label"],
        "last_checked": check_date,
        "last_changed": check_date,
    })
    save_state(state)
    print("\n✓ Done.")


if __name__ == "__main__":
    main()

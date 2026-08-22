#!/usr/bin/env python3
"""
Document Change Monitor
Checks a .docx file at a URL for changes, uses Claude to generate a change log,
and emails a distribution list with the results.
"""

import os
import sys
import json
import hashlib
import smtplib
import requests
import subprocess
import datetime
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import anthropic

# ── Config (loaded from environment variables set in GitHub Actions secrets) ──
DOC_URL         = os.environ["DOC_URL"]           # URL of the .docx to monitor
EMAIL_SENDER    = os.environ["EMAIL_SENDER"]       # Gmail address sending the email
EMAIL_PASSWORD  = os.environ["EMAIL_PASSWORD"]     # Gmail App Password (not your real password)
EMAIL_RECIPIENTS = os.environ["EMAIL_RECIPIENTS"]  # Comma-separated list of recipients
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
DOC_NAME        = os.environ.get("DOC_NAME", "Owner Standards Document")

# Paths
DATA_DIR      = Path("data")
STATE_FILE    = DATA_DIR / "state.json"
PREV_DOC_PATH = DATA_DIR / "previous.docx"
CURR_DOC_PATH = DATA_DIR / "current.docx"
LOG_FILE      = DATA_DIR / "change_log.json"

DATA_DIR.mkdir(exist_ok=True)


# ── Utilities ────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"last_hash": None, "last_checked": None, "last_changed": None, "version": 0}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def download_doc(url: str, dest: Path) -> bool:
    """Download document. Returns True on success."""
    try:
        r = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        dest.write_bytes(r.content)
        return True
    except Exception as e:
        print(f"ERROR: Failed to download document: {e}")
        return False


def extract_text(docx_path: Path) -> str:
    """Extract plain text from a .docx using pandoc."""
    try:
        result = subprocess.run(
            ["pandoc", "--to=plain", "--wrap=none", str(docx_path)],
            capture_output=True, text=True, check=True
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"WARNING: pandoc failed: {e.stderr}")
        # Fallback: python-docx
        try:
            from docx import Document
            doc = Document(str(docx_path))
            return "\n".join(p.text for p in doc.paragraphs)
        except Exception as e2:
            print(f"ERROR: Both extraction methods failed: {e2}")
            return ""


# ── Claude Change Analysis ────────────────────────────────────────────────────

def analyze_changes_with_claude(prev_text: str, curr_text: str, doc_name: str) -> dict:
    """Send both document texts to Claude and get a structured change log."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = f"""You are a technical document analyst for a mechanical engineering consulting firm.

You are comparing two versions of a design and construction standards document titled: "{doc_name}"

Your job is to produce a change log that engineers will use to understand what requirements have changed. 
Focus on changes that affect how they design or specify systems — new requirements, deleted requirements, 
modified dimensions/values/specifications, renamed sections, and any new definitions.

Return ONLY a JSON object with this exact structure (no markdown, no preamble):
{{
  "executive_summary": "2-4 sentence plain English summary of the most important changes",
  "impact_level": "HIGH | MEDIUM | LOW",
  "impact_rationale": "One sentence explaining the impact level rating",
  "changes": [
    {{
      "section": "Section name or number",
      "change_type": "ADDED | DELETED | MODIFIED | RENAMED",
      "description": "Plain English description of what changed",
      "old_text": "Relevant old text snippet (or null if ADDED)",
      "new_text": "Relevant new text snippet (or null if DELETED)",
      "engineering_note": "Why this matters for design/specification (or null if not significant)"
    }}
  ],
  "new_sections": ["List of entirely new section titles"],
  "deleted_sections": ["List of entirely removed section titles"],
  "total_changes": <integer count of changes array>
}}

--- PREVIOUS VERSION ---
{prev_text[:40000]}

--- CURRENT VERSION ---
{curr_text[:40000]}
"""

    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.content[0].text.strip()
    # Strip any accidental markdown fences
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip().rstrip("```").strip()

    return json.loads(raw)


# ── Email Composition ─────────────────────────────────────────────────────────

IMPACT_COLORS = {
    "HIGH":   ("#dc2626", "#fef2f2"),   # red
    "MEDIUM": ("#d97706", "#fffbeb"),   # amber
    "LOW":    ("#16a34a", "#f0fdf4"),   # green
}

CHANGE_TYPE_BADGES = {
    "ADDED":    ("#16a34a", "ADDED"),
    "DELETED":  ("#dc2626", "DELETED"),
    "MODIFIED": ("#2563eb", "MODIFIED"),
    "RENAMED":  ("#7c3aed", "RENAMED"),
}

def build_html_email(change_data: dict, doc_name: str, version: int, check_date: str) -> str:
    impact = change_data.get("impact_level", "MEDIUM")
    impact_color, impact_bg = IMPACT_COLORS.get(impact, ("#6b7280", "#f9fafb"))
    changes = change_data.get("changes", [])
    total = change_data.get("total_changes", len(changes))

    # Build change rows
    change_rows = ""
    for c in changes:
        ct = c.get("change_type", "MODIFIED")
        badge_color, badge_label = CHANGE_TYPE_BADGES.get(ct, ("#6b7280", ct))
        old_snippet = f'<div style="background:#fef2f2;border-left:3px solid #dc2626;padding:6px 10px;margin:4px 0;font-family:monospace;font-size:12px;color:#7f1d1d;">{c["old_text"]}</div>' if c.get("old_text") else ""
        new_snippet = f'<div style="background:#f0fdf4;border-left:3px solid #16a34a;padding:6px 10px;margin:4px 0;font-family:monospace;font-size:12px;color:#14532d;">{c["new_text"]}</div>' if c.get("new_text") else ""
        eng_note    = f'<div style="background:#eff6ff;border-left:3px solid #2563eb;padding:6px 10px;margin:6px 0;font-size:12px;color:#1e40af;">⚙️ <strong>Engineering note:</strong> {c["engineering_note"]}</div>' if c.get("engineering_note") else ""

        change_rows += f"""
        <tr>
          <td style="padding:14px 16px;border-bottom:1px solid #e5e7eb;vertical-align:top;width:140px;">
            <span style="background:{badge_color};color:white;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700;letter-spacing:0.5px;">{badge_label}</span>
            <div style="margin-top:6px;font-size:12px;color:#6b7280;font-weight:600;">{c.get('section','—')}</div>
          </td>
          <td style="padding:14px 16px;border-bottom:1px solid #e5e7eb;vertical-align:top;">
            <div style="color:#111827;margin-bottom:6px;">{c.get('description','')}</div>
            {old_snippet}{new_snippet}{eng_note}
          </td>
        </tr>"""

    new_sec_rows = "".join(
        f'<li style="color:#15803d;">{s}</li>'
        for s in change_data.get("new_sections", [])
    )
    del_sec_rows = "".join(
        f'<li style="color:#dc2626;text-decoration:line-through;">{s}</li>'
        for s in change_data.get("deleted_sections", [])
    )
    structural_block = ""
    if new_sec_rows or del_sec_rows:
        structural_block = f"""
        <div style="margin:24px 0;padding:16px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;">
          <h3 style="margin:0 0 10px;font-size:14px;color:#374151;">Structural Changes</h3>
          <div style="display:flex;gap:32px;">
            {"<div><strong style='color:#15803d;font-size:12px;'>NEW SECTIONS</strong><ul style='margin:6px 0;padding-left:18px;font-size:13px;'>" + new_sec_rows + "</ul></div>" if new_sec_rows else ""}
            {"<div><strong style='color:#dc2626;font-size:12px;'>REMOVED SECTIONS</strong><ul style='margin:6px 0;padding-left:18px;font-size:13px;'>" + del_sec_rows + "</ul></div>" if del_sec_rows else ""}
          </div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <div style="max-width:700px;margin:32px auto;background:white;border-radius:12px;overflow:hidden;box-shadow:0 4px 16px rgba(0,0,0,0.08);">

    <!-- Header -->
    <div style="background:#1e3a5f;padding:28px 32px;">
      <div style="color:#93c5fd;font-size:11px;font-weight:700;letter-spacing:1px;text-transform:uppercase;margin-bottom:4px;">Document Monitor Alert</div>
      <h1 style="margin:0;color:white;font-size:22px;font-weight:700;">{doc_name}</h1>
      <div style="color:#bfdbfe;font-size:13px;margin-top:6px;">Version {version} detected · {check_date}</div>
    </div>

    <!-- Impact Banner -->
    <div style="background:{impact_bg};border-bottom:1px solid {impact_color}20;padding:16px 32px;display:flex;align-items:center;gap:12px;">
      <span style="background:{impact_color};color:white;padding:4px 12px;border-radius:20px;font-size:12px;font-weight:700;">{impact} IMPACT</span>
      <span style="color:{impact_color};font-size:13px;">{change_data.get('impact_rationale','')}</span>
    </div>

    <div style="padding:24px 32px;">

      <!-- Executive Summary -->
      <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:18px;margin-bottom:24px;">
        <div style="font-size:11px;font-weight:700;color:#64748b;letter-spacing:0.8px;text-transform:uppercase;margin-bottom:8px;">Summary</div>
        <p style="margin:0;color:#1e293b;font-size:14px;line-height:1.6;">{change_data.get('executive_summary','')}</p>
      </div>

      <!-- Stats -->
      <div style="display:flex;gap:12px;margin-bottom:24px;">
        <div style="flex:1;text-align:center;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:14px;">
          <div style="font-size:28px;font-weight:700;color:#1e3a5f;">{total}</div>
          <div style="font-size:11px;color:#64748b;text-transform:uppercase;font-weight:600;">Total Changes</div>
        </div>
        <div style="flex:1;text-align:center;background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:14px;">
          <div style="font-size:28px;font-weight:700;color:#15803d;">{sum(1 for c in changes if c.get('change_type')=='ADDED')}</div>
          <div style="font-size:11px;color:#15803d;text-transform:uppercase;font-weight:600;">Added</div>
        </div>
        <div style="flex:1;text-align:center;background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:14px;">
          <div style="font-size:28px;font-weight:700;color:#dc2626;">{sum(1 for c in changes if c.get('change_type')=='DELETED')}</div>
          <div style="font-size:11px;color:#dc2626;text-transform:uppercase;font-weight:600;">Deleted</div>
        </div>
        <div style="flex:1;text-align:center;background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;padding:14px;">
          <div style="font-size:28px;font-weight:700;color:#2563eb;">{sum(1 for c in changes if c.get('change_type')=='MODIFIED')}</div>
          <div style="font-size:11px;color:#2563eb;text-transform:uppercase;font-weight:600;">Modified</div>
        </div>
      </div>

      {structural_block}

      <!-- Detailed Change Table -->
      <h3 style="margin:0 0 12px;font-size:15px;color:#1e293b;">Detailed Change Log</h3>
      <table style="width:100%;border-collapse:collapse;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;font-size:13px;">
        <thead>
          <tr style="background:#f8fafc;">
            <th style="padding:10px 16px;text-align:left;font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;border-bottom:1px solid #e5e7eb;">Type / Section</th>
            <th style="padding:10px 16px;text-align:left;font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;border-bottom:1px solid #e5e7eb;">Change Description</th>
          </tr>
        </thead>
        <tbody>{change_rows}</tbody>
      </table>

    </div>

    <!-- Footer -->
    <div style="background:#f8fafc;border-top:1px solid #e5e7eb;padding:16px 32px;font-size:11px;color:#94a3b8;text-align:center;">
      Automated by AAME Document Monitor · {check_date} · Reply to this email to unsubscribe
    </div>
  </div>
</body></html>"""
    return html


def build_plain_text_email(change_data: dict, doc_name: str, version: int, check_date: str) -> str:
    lines = [
        f"DOCUMENT CHANGE ALERT — {doc_name}",
        f"Version {version} detected on {check_date}",
        "=" * 60,
        "",
        f"IMPACT LEVEL: {change_data.get('impact_level','UNKNOWN')}",
        f"{change_data.get('impact_rationale','')}",
        "",
        "SUMMARY",
        "-" * 40,
        change_data.get("executive_summary", ""),
        "",
        "DETAILED CHANGES",
        "-" * 40,
    ]
    for c in change_data.get("changes", []):
        lines.append(f"\n[{c.get('change_type','?')}] {c.get('section','')}")
        lines.append(f"  {c.get('description','')}")
        if c.get("old_text"):
            lines.append(f"  BEFORE: {c['old_text']}")
        if c.get("new_text"):
            lines.append(f"  AFTER:  {c['new_text']}")
        if c.get("engineering_note"):
            lines.append(f"  NOTE:   {c['engineering_note']}")
    if change_data.get("new_sections"):
        lines += ["", "NEW SECTIONS:", *[f"  + {s}" for s in change_data["new_sections"]]]
    if change_data.get("deleted_sections"):
        lines += ["", "DELETED SECTIONS:", *[f"  - {s}" for s in change_data["deleted_sections"]]]
    lines += ["", "-" * 60, "Automated by AAME Document Monitor"]
    return "\n".join(lines)


def send_email(html_body: str, plain_body: str, doc_name: str, version: int, attachment_path: Path):
    recipients = [r.strip() for r in EMAIL_RECIPIENTS.split(",") if r.strip()]
    subject = f"[Doc Update] {doc_name} — Version {version} Detected"

    msg = MIMEMultipart("mixed")
    msg["From"]    = EMAIL_SENDER
    msg["To"]      = ", ".join(recipients)
    msg["Subject"] = subject

    # Multipart/alternative for HTML + plain text
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(plain_body, "plain"))
    alt.attach(MIMEText(html_body, "html"))
    msg.attach(alt)

    # Attach the new document
    if attachment_path.exists():
        with open(attachment_path, "rb") as f:
            part = MIMEBase("application", "vnd.openxmlformats-officedocument.wordprocessingml.document")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{doc_name}_v{version}.docx"')
        msg.attach(part)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, recipients, msg.as_string())
    print(f"✓ Email sent to: {', '.join(recipients)}")


def append_log(change_data: dict, version: int, check_date: str):
    log = []
    if LOG_FILE.exists():
        log = json.loads(LOG_FILE.read_text())
    log.append({
        "version": version,
        "detected_at": check_date,
        "impact_level": change_data.get("impact_level"),
        "executive_summary": change_data.get("executive_summary"),
        "total_changes": change_data.get("total_changes"),
        "changes": change_data.get("changes", []),
    })
    LOG_FILE.write_text(json.dumps(log, indent=2))
    print(f"✓ Change log updated ({len(log)} entries total)")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    check_date = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n{'='*60}")
    print(f"Document Monitor — {check_date}")
    print(f"Checking: {DOC_URL}")
    print(f"{'='*60}")

    state = load_state()

    # Download current version
    print("\n→ Downloading document...")
    if not download_doc(DOC_URL, CURR_DOC_PATH):
        sys.exit(1)

    current_hash = file_hash(CURR_DOC_PATH)
    print(f"  Hash: {current_hash[:16]}...")

    # Compare with previous
    if state["last_hash"] == current_hash:
        print("\n✓ No change detected. Document is unchanged.")
        state["last_checked"] = check_date
        save_state(state)
        return

    print("\n⚠ CHANGE DETECTED — document hash differs from previous version")

    # First run — no previous version to compare against
    if state["last_hash"] is None:
        print("  First run — storing baseline. No email sent.")
        import shutil
        shutil.copy(CURR_DOC_PATH, PREV_DOC_PATH)
        state.update({
            "last_hash": current_hash,
            "last_checked": check_date,
            "last_changed": check_date,
            "version": 1,
        })
        save_state(state)
        print("✓ Baseline stored. Future changes will trigger email alerts.")
        return

    # Extract text from both versions
    print("\n→ Extracting text from both versions...")
    prev_text = extract_text(PREV_DOC_PATH)
    curr_text = extract_text(CURR_DOC_PATH)
    print(f"  Previous: {len(prev_text):,} chars | Current: {len(curr_text):,} chars")

    # Claude analysis
    print("\n→ Analyzing changes with Claude...")
    change_data = analyze_changes_with_claude(prev_text, curr_text, DOC_NAME)
    print(f"  Impact: {change_data.get('impact_level')} | Changes found: {change_data.get('total_changes')}")

    # Build emails
    version = state["version"] + 1
    html_body  = build_html_email(change_data, DOC_NAME, version, check_date)
    plain_body = build_plain_text_email(change_data, DOC_NAME, version, check_date)

    # Send email
    print("\n→ Sending email notification...")
    send_email(html_body, plain_body, DOC_NAME, version, CURR_DOC_PATH)

    # Update log and state
    append_log(change_data, version, check_date)

    import shutil
    shutil.copy(CURR_DOC_PATH, PREV_DOC_PATH)
    state.update({
        "last_hash": current_hash,
        "last_checked": check_date,
        "last_changed": check_date,
        "version": version,
    })
    save_state(state)
    print(f"\n✓ Done. Version {version} stored as new baseline.")

    # Update to claude-sonnet-5

if __name__ == "__main__":
    main()

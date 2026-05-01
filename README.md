# AAME Document Change Monitor

Automatically checks a `.docx` standards document for updates on a schedule, 
uses Claude AI to produce a detailed engineering-focused change log, and emails 
your team with a summary + full breakdown. The updated document is attached.

---

## How It Works

```
GitHub Actions (weekly cron)
  → Download .docx from URL
  → Compare SHA-256 hash with stored previous version
  → If changed: extract text from both, send to Claude for analysis
  → Claude returns structured change log (impact level, section-by-section diff)
  → Send HTML email with change log + new document attached
  → Commit updated state back to repo (stores new baseline)
```

State (previous document + change log) lives in the `data/` directory, 
committed back to the repo after each run. No database needed.

---

## Setup (one-time, ~15 minutes)

### Step 1: Create the GitHub Repository

1. Go to [github.com](https://github.com) and sign in (create a free account if needed)
2. Click **New repository**
3. Name it `doc-monitor` (or anything you like), set to **Private**
4. Do **not** initialize with README (you'll push these files)
5. Click **Create repository**

### Step 2: Push These Files

On your computer, open a terminal (or Git Bash on Windows):

```bash
cd path/to/this/folder   # wherever you unzipped these files
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/doc-monitor.git
git push -u origin main
```

### Step 3: Set Up Gmail App Password

The monitor sends email via Gmail. You need an **App Password** (not your real password):

1. Go to your Google Account → **Security**
2. Enable **2-Step Verification** if not already on
3. Search for **App passwords** (or go to myaccount.google.com/apppasswords)
4. Create one: name it "Doc Monitor", select "Mail"
5. Copy the 16-character password — you'll use it as `EMAIL_PASSWORD`

### Step 4: Add GitHub Secrets

In your GitHub repo, go to **Settings → Secrets and variables → Actions → New repository secret**

Add each of the following:

| Secret Name | Value | Example |
|-------------|-------|---------|
| `DOC_URL` | Direct download URL of the .docx file | `https://owner.gov/standards/design-standards.docx` |
| `DOC_NAME` | Human-readable document name | `RTAA Design & Construction Standards` |
| `EMAIL_SENDER` | Your Gmail address | `you@gmail.com` |
| `EMAIL_PASSWORD` | Gmail App Password from Step 3 | `abcd efgh ijkl mnop` |
| `EMAIL_RECIPIENTS` | Comma-separated recipient emails | `you@aame.com, colleague@aame.com` |
| `ANTHROPIC_API_KEY` | Your Anthropic API key | `sk-ant-...` |

**Getting an Anthropic API key:**
- Go to [console.anthropic.com](https://console.anthropic.com)
- Sign up / log in → API Keys → Create Key
- Add a small credit (~$5 covers hundreds of checks)

### Step 5: Run It Once to Set Baseline

1. In your GitHub repo, go to **Actions**
2. Click **Document Change Monitor** in the left sidebar
3. Click **Run workflow** → **Run workflow**
4. Watch the logs — first run stores the baseline, no email is sent
5. Run it a second time to confirm it detects "no change" correctly

---

## Configuration

### Change the Check Schedule

Edit `.github/workflows/monitor.yml`, find the `cron:` line:

```yaml
- cron: "0 8 * * 1"    # Every Monday at 8am UTC
- cron: "0 8 * * 1-5"  # Weekdays at 8am UTC  
- cron: "0 8 * * *"    # Daily at 8am UTC
- cron: "0 8 * * 1,4"  # Monday + Thursday
```

UTC is 7 hours ahead of Mountain Time (8 hours during daylight saving).
So `0 15 * * 1` = Monday at 8am Mountain (standard time).

### Add More Documents

Duplicate the workflow file and monitor script with different secret names 
(e.g., `DOC_URL_2`, `DOC_NAME_2`) to monitor multiple documents.

### Monitoring a Document Behind Login

If the document URL requires authentication:
- Check if there's a direct download token/link in the URL
- Some systems provide a "share link" with an embedded token
- For SharePoint: use the "direct link" with `download=1` parameter

---

## File Structure

```
doc-monitor/
├── .github/
│   └── workflows/
│       └── monitor.yml        ← Schedule + GitHub Actions config
├── scripts/
│   └── monitor.py             ← Main monitoring script
├── data/
│   ├── .gitkeep               ← Keeps directory in git
│   ├── state.json             ← Created on first run (hash, version, dates)
│   ├── previous.docx          ← Last confirmed version of the document
│   └── change_log.json        ← Cumulative history of all detected changes
├── requirements.txt
├── .gitignore
└── README.md
```

---

## Reading the Change Log

`data/change_log.json` accumulates every detected change across all versions:

```json
[
  {
    "version": 2,
    "detected_at": "2025-06-02 08:00 UTC",
    "impact_level": "HIGH",
    "executive_summary": "Section 4.3 updated pipe insulation requirements...",
    "total_changes": 7,
    "changes": [
      {
        "section": "4.3 Pipe Insulation",
        "change_type": "MODIFIED",
        "description": "Minimum insulation thickness for CHW supply increased",
        "old_text": "1-inch minimum thickness for pipes ≤ 2\"",
        "new_text": "1.5-inch minimum thickness for pipes ≤ 2\"",
        "engineering_note": "Affects pipe insulation specs on all hydronic projects"
      }
    ]
  }
]
```

---

## Cost

- **GitHub Actions**: Free for private repos (2,000 minutes/month; each run ≈ 1-2 min)
- **Claude API**: ~$0.01–0.05 per change detection (only charged when document changes)
- **Gmail**: Free
- **Total ongoing cost**: Effectively $0/month unless document changes very frequently

---

## Troubleshooting

**"Download failed"** — The URL may require login, have changed, or use a redirect.
Test the URL in an incognito browser tab.

**"pandoc failed"** — Fallback (python-docx) will be used automatically.

**Email not received** — Check Gmail App Password, verify 2FA is on, check spam folder.

**"No changes detected" but document updated** — Some owners update metadata without 
changing content; the hash covers all bytes. If this is frequent, switch to 
last-modified header checking (open an issue).

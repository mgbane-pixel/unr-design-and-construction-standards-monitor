# UNR Design and Construction Standards Monitor

Watches the [UNR Facilities Services design standards page](https://www.unr.edu/facilities/planning-and-construction/design-construction-standards) for a new document posting and emails a distribution list when it finds one.

## How it works

The Design and Construction Standards document is hosted on Box behind a shared link that requires a signed-in session to download programmatically — there's no reliable way to pull the file itself in an unattended script. So instead of downloading and diffing the document, this tool:

1. On a schedule, fetches the UNR standards page
2. Scrapes out the current Box link and its label (e.g. "Design and Construction Standards: 10/31/2025")
3. Compares that link against the last one it saw (stored in `data/state.json`)
4. If it changed, emails the distribution list with the old link, the new link, and a pointer back to the UNR page

Someone on the list then opens the page, grabs both versions manually, and — if a written comparison is wanted — drops both files into a Claude conversation and asks for a section-by-section change summary. That step is manual by design; see [Manual comparison](#manual-comparison) below.

## Setup

Six values are read from environment variables, set as GitHub Actions secrets under **Settings → Secrets and variables → Actions**:

| Secret | Description |
|---|---|
| `DOC_URL` | The UNR standards webpage URL (not the Box link — the page the Box link lives on) |
| `EMAIL_SENDER` | Gmail address the alert is sent from |
| `EMAIL_PASSWORD` | Gmail [App Password](https://myaccount.google.com/apppasswords) for that address — not the account's real password |
| `EMAIL_RECIPIENTS` | Comma-separated list of addresses to notify (e.g. `person1@aame.com,person2@aame.com`) |
| `DOC_NAME` | Optional. Display name used in the email subject/body. Defaults to "Owner Standards Document" if not set |

GitHub Secrets are write-only once saved — you can update them but not view the current value, so keep a note somewhere of who's on the recipient list before changing it.

## Schedule

Runs on the cron schedule defined in `.github/workflows/monitor.yml`. Can also be triggered manually from the **Actions** tab via **Run workflow**, if that trigger is enabled in the workflow file.

## State

`data/state.json` tracks the last-seen link and label:

```json
{
  "last_link": "https://nevada.box.com/s/...",
  "last_label": "Design and Construction Standards: 10/31/2025",
  "last_checked": "2026-08-22 18:31 UTC",
  "last_changed": "2026-08-22 18:31 UTC"
}
```

The Action needs **read and write** permissions on the repo (Settings → Actions → General → Workflow permissions) so it can commit updates to this file after each run.

The very first run after a schema or setup change stores a baseline silently and sends no email — that's expected, not a failure.

## Manual comparison

Once you have both `.docx` versions downloaded:

1. Start a conversation with Claude
2. Upload the previous and current versions
3. Ask for a section-by-section change summary — flag what's new, deleted, or modified, and note anything that affects design or specification decisions

This used to be automated end-to-end with the Anthropic API, but was cut when the Box download step stopped being reliable for unattended runs. The prompt and structure that used to drive the automated version worked well and can be reused conversationally.

## Troubleshooting

**"Could not find the standards link on the page"** — UNR changed the page layout and the scrape regex in `check_for_page_change()` no longer matches. Check the page's current HTML structure and update the pattern in `scripts/monitor.py`.

**No email on a run that should have found a change** — check `data/state.json` in the repo to confirm `last_link` actually updated on the previous run. If the workflow lacks write permissions, state changes won't persist between runs and every run will look like a change (or none, depending on the failure).

**Gmail auth errors** — App Passwords can be revoked if 2FA settings change on the sending account. Regenerate one at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) and update the `EMAIL_PASSWORD` secret.

# transaction-monitor

Posts a roundup to Slack at 11:00, 17:00 and 23:00 IST: how many card
transactions were detected in `#otp-bridge` since midnight, which are logged
in the Finances Tracker, which are still pending, and which ops have excluded.

## How matching works
- One ICICI parser handles all three cards (keyed on card last-4).
- Retries collapsed: same card + same amount within 10 min = one transaction.
- **Excluded by ops:** react to an `#otp-bridge` message with :x: to void a
  transaction (refund, failed attempt, etc.). It's then counted as *excluded*
  instead of pending and never needs logging. Optionally reply in-thread with a
  short note — the first human reply becomes the "Reason" in the excluded
  table. An :x: on *any* message in a retry cluster excludes the whole cluster.
- Match key: **Date + Payment method + Amount (±₹5)**. Platform is a
  tie-breaker only, so a missing alias never creates a false "pending".
- Rows are consumed one-to-one (greedy), so counts don't double up.
- Household tabs are auto-detected by header row — new households cloned from
  "Duplicate me" are picked up automatically; Legend/To fix/Master Tracker/
  exports are skipped.

## What you edit
Almost everything lives in `src/config.py`: the card→payment-method map, the
merchant alias map (extend from your scraped distinct merchant strings), the
±5 tolerance, and the 10-minute dedup window.

---

## Setup

### 1. Slack app
1. https://api.slack.com/apps → **Create New App** → From scratch → pick your workspace.
2. **OAuth & Permissions** → Bot Token Scopes: add `channels:history` and
   `chat:write` (use `groups:history` instead if `#otp-bridge` is private).
   No extra scope is needed for the :x: void reactions — `conversations.history`
   includes a `reactions` array, and `conversations.replies` (for the reason
   note) is also covered by `channels:history`.
3. **Install to Workspace**, copy the **Bot User OAuth Token** (`xoxb-...`).
4. In Slack, invite the bot to both channels: `/invite @yourbot` in
   `#otp-bridge` and in your new summary channel.
5. Channel IDs: open each channel → channel name → bottom of the popup shows
   an ID like `C0xxxxxxx`. Grab both.

### 2. Google Sheets API (keyless — Workload Identity Federation)
Downloadable service-account keys are blocked by org policy, so GitHub
authenticates via short-lived OIDC tokens instead. No key file ever exists.
Run these in Cloud Shell (you need Owner/IAM-admin on the project — being the
project creator is enough; no org admin required):

```bash
export PROJECT_ID="your-project-id"
export REPO="siddharth-curious-inc/transaction-monitor"          # GitHub owner/repo
export SA_NAME="transaction-monitor"
export PROJECT_NUMBER="$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')"
export SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

# enable APIs
gcloud services enable iamcredentials.googleapis.com sheets.googleapis.com --project $PROJECT_ID

# service account = identity to impersonate (NO key)
gcloud iam service-accounts create $SA_NAME --project $PROJECT_ID --display-name "Transaction monitor"

# workload identity pool + GitHub OIDC provider, locked to your repo
gcloud iam workload-identity-pools create github-pool \
  --project $PROJECT_ID --location global --display-name "GitHub pool"

gcloud iam workload-identity-pools providers create-oidc github-provider \
  --project $PROJECT_ID --location global --workload-identity-pool github-pool \
  --display-name "GitHub provider" \
  --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition "assertion.repository=='${REPO}'" \
  --issuer-uri "https://token.actions.githubusercontent.com"

# let only your repo impersonate the SA
gcloud iam service-accounts add-iam-policy-binding $SA_EMAIL --project $PROJECT_ID \
  --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/attribute.repository/${REPO}"

# print the two values you'll paste into GitHub secrets
echo "GCP_SA_EMAIL=$SA_EMAIL"
echo "GCP_WIF_PROVIDER=projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/providers/github-provider"
```

Then **share the Finances Tracker workbook with `$SA_EMAIL` as Viewer**, and
note the Sheet ID (the string in the URL between `/d/` and `/edit`).

### 3. Repo + secrets
1. Push this repo to GitHub.
2. Repo → **Settings → Secrets and variables → Actions → New repository secret**.
   Add:
   - `SLACK_BOT_TOKEN`   = the `xoxb-...` token
   - `OTP_CHANNEL_ID`    = `#otp-bridge` channel ID
   - `SUMMARY_CHANNEL_ID`= summary channel ID (point at a **test** channel first)
   - `SHEET_ID`          = the workbook ID
   - `GCP_SA_EMAIL`      = printed by the script above
   - `GCP_WIF_PROVIDER`  = printed by the script above

### 4. Test before going live
- Local: `pip install -r requirements.txt && python -m pytest tests/ -q`
- Full pipeline, no posting: `gcloud auth application-default login` once
  (logs in as you; you already have access to the sheet), set the Slack env
  vars, then `python src/run.py --dry-run` — reads real Slack + Sheets, prints
  the message instead of posting.
- In GitHub: **Actions → transaction-monitor-roundup → Run workflow**, tick `dry_run`.
- When happy, point `SUMMARY_CHANNEL_ID` at the real channel. The schedule is
  already live once the workflow file is on the default branch.

## Notes / limits (MVP)
- An OTP is not a confirmed transaction (retries, failed/abandoned, pre-auth
  vs final amount). Dedup handles retries; the rest is accepted for now.
- GitHub cron can drift a few minutes — fine for a nudge.
- A purchase after the 23:00 run is missed (next day reads from its own
  midnight). Move the last run later if that matters.
- Same card + two amounts within ±5 on the same day can mis-pair; rare.

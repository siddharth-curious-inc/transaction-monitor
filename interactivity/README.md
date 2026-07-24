# Interactivity bot (Finance Tracker helper, Slack Socket Mode)

An always-on process that turns every `#transaction-bridge` debit confirmation
into an interactive prompt in `#otp-bridge`, and writes the chosen household's
row to the Finance Tracker the moment ops triages it. It complements — and does
not replace — the scheduled roundup pipeline in `../src`.

## What it does

- **Polls** `#transaction-bridge` every ~75s (`poller.py`) and posts one prompt
  per new confirmation. Credit-card confirmations are posted as a **threaded
  reply** under the matching `#otp-bridge` OTP (`otp_match.py`: same last-4 +
  amount, strictly earlier, within 30 min, closest-before, never reusing an OTP
  it already answered); UPI (and any CC with no OTP match) post **standalone**.
- The prompt (`blocks.py`) shows the condensed transaction and an **alphabetical
  household dropdown** (plus an **Exclude** option) and a **Remark** button that
  opens a modal (free-text remark; input fields can only live in a modal).
- **On a household selection** (`handlers.py` → `service.py`): append the row via
  the Sheets `values.append` + `INSERT_ROWS` (atomic; no empty-row scan), Date
  written `DD-Mon-YYYY` to match the pipeline's matcher. The prompt updates to
  ✅ + household + user, and a **:white_check_mark: reaction** is added to the
  **top-level** message (OTP parent for CC, the prompt itself for UPI) so ops see
  it's resolved at a glance without opening the thread.
- **On Exclude**: the prompt updates to 🚫 and its Slack **message metadata** is
  set to `state=excluded`. The scheduled pipeline reads that
  (`slack_io.fetch_bot_prompt_states` → `run.apply_bot_exclusions`) and drops the
  item from pending — the dropdown Exclude supersedes the `:x:` reaction for new
  transactions. (The legacy `:x:` reading still runs for old OTP messages.)

State is reconstructed from the bot's own prompts (each carries its originating
`#transaction-bridge` ts in message metadata), so restarts don't double-prompt
and need no external store.

## Auth / config

Environment variables (never hardcoded):

| Var | What |
|---|---|
| `SLACK_BOT_TOKEN` | `xoxb-` bot token. Scopes: `chat:write`, `reactions:write`, `*:history`. |
| `SLACK_APP_TOKEN` | `xapp-` app-level token with **`connections:write`** (Socket Mode). |
| `SHEET_ID` | Finance Tracker workbook id. |
| `OTP_CHANNEL_ID` / `TRANSACTION_CHANNEL_ID` | Override to point at a scratch channel. |
| `DRY_RUN` | `1` to print the sheet write instead of performing it (messages still update). |
| `PORT` | Cloud Run health port (defaults 8080). |

Sheets access is the **ambient attached service account** on Cloud Run (no key
file). Personal `gcloud` ADC is blocked by org policy here, so anywhere the SA
identity isn't ambient (e.g. a laptop) needs a WIF-derived credential the SA can
assume — the bot always needs Sheets read to build the household dropdown.

## Message format (important)

The bot parses the **production `#transaction-bridge` Block Kit** shape:
`header` + a `section` with `*Raw SMS:*` + a `section` of fields + a `context`
footer (see `tests/fixtures/transaction_messages.json`). Copy-pasting a message
that Slack already *rendered* produces a single `rich_text` block instead, which
the parser does not read — so don't test by pasting a rendered message. Use the
poster below, which emits the production shape.

## Post sample transactions to a scratch channel

```bash
python tools/post_sample_txn.py verify   # parse locally, post nothing
python tools/post_sample_txn.py upi       # a UPI debit -> standalone prompt
python tools/post_sample_txn.py card      # an OTP + a card debit -> threaded prompt
python tools/post_sample_txn.py all        # both (default)
```

## Run locally (test against a scratch channel + scratch tab)

Socket Mode dials out, so the bot runs identically on a laptop, given Sheets
access (see above):

```bash
pip install -r ../requirements.txt
cp ../.env.example ../.env    # fill in SLACK_BOT_TOKEN + SLACK_APP_TOKEN

python app.py
```

`.env` (loaded by `config.py`) supplies the tokens + scratch `SHEET_ID` /
channel ids. Then post a sample (above) and drive the prompt → dropdown → modal
→ Exclude flows. Kill and restart the process to confirm it does not re-prompt
an already-handled item.

## Test the Sheets write in CI (WIF)

Because personal ADC is blocked, the household-row write is validated in GitHub
Actions under Workload Identity Federation via the **`test-bot-sheets`** workflow
(`.github/workflows/test-bot-sheets.yml`): it runs the unit suite, then
`tools/sheet_write_smoke.py` to append a test row to a scratch tab and confirm it
reads back in a matcher-parseable shape. The WIF service account must have Editor
access to the scratch workbook.

## Deploy (Cloud Run)

Exactly one always-on instance (two would double-handle events), no public
endpoint (Socket Mode only):

```bash
docker build -f interactivity/Dockerfile -t REGION-docker.pkg.dev/PROJECT/REPO/finance-tracker-bot .
docker push REGION-docker.pkg.dev/PROJECT/REPO/finance-tracker-bot

gcloud run deploy finance-tracker-bot \
  --image REGION-docker.pkg.dev/PROJECT/REPO/finance-tracker-bot \
  --no-allow-unauthenticated \
  --min-instances=1 --max-instances=1 \
  --service-account transaction-monitor@PROJECT.iam.gserviceaccount.com \
  --set-secrets SLACK_BOT_TOKEN=SLACK_BOT_TOKEN:latest,SLACK_APP_TOKEN=SLACK_APP_TOKEN:latest \
  --set-env-vars SHEET_ID=...
```

Slack app config: enable **Socket Mode**, create the `xapp-` token with
`connections:write`, add the bot scope `reactions:write` (the history + chat
scopes already exist for the pipeline). The Interactivity "Request URL" stays
disabled.
```

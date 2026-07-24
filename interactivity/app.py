"""Entry point for the Finance Tracker interactivity bot (Slack Socket Mode).

One always-on process with three concurrent parts:
  1. a Socket Mode connection receiving interaction events (handlers.py);
  2. a poll loop posting prompts for new #transaction-bridge txns (poller.py);
  3. a health server on $PORT for Cloud Run (health.py).

Auth: SLACK_BOT_TOKEN (xoxb-) + SLACK_APP_TOKEN (xapp-, connections:write), both
from the environment (mounted from Secret Manager on Cloud Run). Sheets access
is the ambient attached service account (ADC) -- no key file. Run locally with
the two tokens set and `gcloud auth application-default login` for Sheets.
"""
import os
import sys
import threading
from pathlib import Path

# Point OpenSSL at certifi's CA bundle if the platform's default trust store is
# incomplete (common with python.org builds / slim containers), so both the Web
# API client and the Socket Mode WebSocket can verify Slack's certificate. Only
# sets it when unset, so a correctly-configured host/Cloud Run is unaffected.
try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
except ImportError:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from slack_bolt import App  # noqa: E402
from slack_bolt.adapter.socket_mode import SocketModeHandler  # noqa: E402
from slack_sdk.http_retry.builtin_handlers import (  # noqa: E402
    RateLimitErrorRetryHandler)

import handlers  # noqa: E402
from config import DRY_RUN, SLACK_APP_TOKEN, SLACK_BOT_TOKEN  # noqa: E402
from health import start_health_server  # noqa: E402
from poller import run_poll_loop  # noqa: E402


def build_app():
    if not SLACK_BOT_TOKEN or not SLACK_APP_TOKEN:
        raise SystemExit(
            "SLACK_BOT_TOKEN and SLACK_APP_TOKEN must both be set "
            "(xapp- app-level token needs the connections:write scope).")
    app = App(token=SLACK_BOT_TOKEN)
    app.client.retry_handlers.append(RateLimitErrorRetryHandler(max_retry_count=5))
    handlers.register(app)
    return app


def main():
    app = build_app()
    start_health_server()
    threading.Thread(target=run_poll_loop, args=(app.client,),
                     daemon=True).start()
    print(f"[bot] starting Socket Mode listener (dry_run={DRY_RUN})")
    SocketModeHandler(app, SLACK_APP_TOKEN).start()


if __name__ == "__main__":
    main()

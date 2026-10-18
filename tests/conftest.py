import os

# Tests run on the deterministic planner whatever .env says (a developer's key must not make the suite slow,
# flaky or billable). Real env vars win over .env in Settings, so this is enough; tests that need another
# provider set it explicitly (test_api.py's env fixture).
os.environ.setdefault("LLM_PROVIDER", "mock")
# Tests never post to the real Slack channel or accept real Slack requests, whatever .env holds (an empty env var
# wins over .env). Tests that need Slack set their own values.
os.environ.setdefault("SLACK_WEBHOOK_URL", "")
os.environ.setdefault("SLACK_SIGNING_SECRET", "")

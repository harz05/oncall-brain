"""Optional outbound hook: post the comms agent's status update to a Slack channel through an incoming webhook
(SLACK_WEBHOOK_URL). Off when unset. A failed post never fails the incident: it is reported, not raised."""

import httpx

from oncall_brain.config import get_settings


def post(text: str | None) -> str:
    """"off" (no webhook configured or nothing to say), "posted", or "failed (<error type>)"."""
    url = get_settings().slack_webhook_url
    if not url or not text:
        return "off"
    try:
        httpx.post(url, json={"text": text}, timeout=5).raise_for_status()
        return "posted"
    except httpx.HTTPError as e:
        return f"failed ({type(e).__name__})"  # never the URL: it is the secret

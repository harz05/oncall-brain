"""Optional outbound hook: post the comms agent's status update to a Slack channel through an incoming webhook
(SLACK_WEBHOOK_URL). Off when unset. A failed post never fails the incident: it is reported, not raised."""

import httpx

from oncall_brain.config import get_settings


def post(text: str | None) -> str:
    """"off" (no webhook configured), "nothing to post", "posted", or "failed: <what Slack or the network said>"
    (never the URL: it is the secret)."""
    url = get_settings().slack_webhook_url
    if not url:
        return "off"
    if not text:
        return "nothing to post"
    # Slack control sequences (<!channel>, <url|label>) can come from public input: escape as Slack documents.
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    try:
        httpx.post(url, json={"text": text}, timeout=5).raise_for_status()
        return "posted"
    except httpx.HTTPStatusError as e:
        return f"failed: Slack answered {e.response.status_code} (is SLACK_WEBHOOK_URL a live incoming webhook?)"
    except httpx.HTTPError as e:
        return f"failed: {type(e).__name__} reaching Slack (network, DNS or the URL)"

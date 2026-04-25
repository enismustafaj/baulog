"""Slack webhook handler for receiving Slack messages and events."""

from typing import Any
from datetime import datetime
from pydantic import BaseModel


class SlackMessage(BaseModel):
    """Slack message payload model."""

    channel: str
    user: str
    text: str
    timestamp: str | None = None
    thread_ts: str | None = None
    reactions: list[str] | None = None
    files: list[dict] | None = None


class SlackEvent(BaseModel):
    """Slack event wrapper model."""

    type: str  # message, app_mention, file_shared, etc.
    event: SlackMessage
    team_id: str | None = None
    api_app_id: str | None = None
    event_id: str | None = None
    event_time: int | None = None


class SlackWebhookHandler:
    """Handler for processing Slack webhook data."""

    @staticmethod
    def parse_slack_message(payload: SlackEvent) -> str:
        """Convert Slack message/event into formatted text for agent evaluation.

        Args:
            payload: Slack webhook payload

        Returns:
            Formatted Slack message text for evaluation
        """
        event = payload.event
        slack_text = f"""
SLACK MESSAGE
=============
Channel: {event.channel}
User: {event.user}
Event Type: {payload.type}
Timestamp: {event.timestamp or datetime.now().isoformat()}

MESSAGE:
{event.text}

"""
        if event.thread_ts:
            slack_text += f"Thread: {event.thread_ts}\n"

        if event.reactions:
            slack_text += f"Reactions: {', '.join(event.reactions)}\n"

        if event.files:
            slack_text += f"Files: {len(event.files)} attachment(s)\n"
            for file in event.files:
                slack_text += f"  - {file.get('name', 'Unknown')} ({file.get('mimetype', 'unknown')})\n"

        return slack_text

    @staticmethod
    def validate_slack_signature(
        timestamp: str, signature: str, body: str, signing_secret: str
    ) -> bool:
        """Validate Slack request signature for security.

        Args:
            timestamp: Request timestamp from Slack
            signature: Provided signature from Slack
            body: Raw request body
            signing_secret: Slack signing secret

        Returns:
            True if signature is valid, False otherwise
        """
        import hmac
        import hashlib
        import time

        # Check if timestamp is recent (within 5 minutes)
        request_time = int(timestamp)
        current_time = int(time.time())
        if abs(current_time - request_time) > 300:
            return False

        # Verify signature
        base_string = f"v0:{timestamp}:{body}"
        expected_signature = (
            "v0="
            + hmac.new(
                signing_secret.encode(),
                base_string.encode(),
                hashlib.sha256,
            ).hexdigest()
        )
        return hmac.compare_digest(signature, expected_signature)

    @staticmethod
    def handle_url_verification(payload: dict) -> dict:
        """Handle Slack URL verification challenge.

        Args:
            payload: Webhook payload from Slack

        Returns:
            Challenge response for URL verification
        """
        if payload.get("type") == "url_verification":
            return {"challenge": payload.get("challenge")}
        return {}

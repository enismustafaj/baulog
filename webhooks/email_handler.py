"""Email webhook handler for receiving email data."""

from typing import Any
from datetime import datetime
from pydantic import BaseModel, EmailStr


class EmailData(BaseModel):
    """Email webhook payload model."""

    sender: EmailStr
    recipients: list[EmailStr]
    subject: str
    body: str
    timestamp: datetime | None = None
    message_id: str | None = None
    cc: list[EmailStr] | None = None
    bcc: list[EmailStr] | None = None
    attachments: list[str] | None = None  # File names or URLs


class EmailWebhookHandler:
    """Handler for processing email webhook data."""

    @staticmethod
    def parse_email_data(payload: EmailData) -> str:
        """Convert email data into a formatted string for agent evaluation.

        Args:
            payload: Email webhook payload

        Returns:
            Formatted email text for evaluation
        """
        email_text = f"""
EMAIL MESSAGE
=============
From: {payload.sender}
To: {", ".join(payload.recipients)}
Subject: {payload.subject}
Timestamp: {payload.timestamp or datetime.now().isoformat()}
Message ID: {payload.message_id or "N/A"}

"""
        if payload.cc:
            email_text += f"CC: {', '.join(payload.cc)}\n"

        if payload.bcc:
            email_text += f"BCC: {', '.join(payload.bcc)}\n"

        email_text += f"\nBODY:\n{payload.body}\n"

        if payload.attachments:
            email_text += f"\nAttachments: {', '.join(payload.attachments)}\n"

        return email_text

    @staticmethod
    def validate_webhook_signature(signature: str, payload: str, secret: str) -> bool:
        """Validate email webhook signature for security.

        Args:
            signature: Provided signature from webhook
            payload: Raw webhook payload
            secret: Shared secret for validation

        Returns:
            True if signature is valid, False otherwise
        """
        import hmac
        import hashlib

        expected_signature = hmac.new(
            secret.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(signature, expected_signature)

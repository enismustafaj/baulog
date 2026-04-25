"""ERP webhook handler for receiving ERP system data."""

from typing import Any
from datetime import datetime
from pydantic import BaseModel


class ERPRecord(BaseModel):
    """ERP record payload model."""

    record_type: str  # purchase_order, invoice, shipment, etc.
    record_id: str
    system: str  # SAP, Oracle, NetSuite, etc.
    data: dict[str, Any]
    timestamp: datetime | None = None
    source_system: str | None = None
    priority: str = "NORMAL"  # HIGH, NORMAL, LOW


class ERPWebhookHandler:
    """Handler for processing ERP webhook data."""

    @staticmethod
    def parse_erp_data(payload: ERPRecord) -> str:
        """Convert ERP record into formatted text for agent evaluation.

        Args:
            payload: ERP webhook payload

        Returns:
            Formatted ERP data text for evaluation
        """
        erp_text = f"""
ERP RECORD
==========
System: {payload.system}
Record Type: {payload.record_type}
Record ID: {payload.record_id}
Priority: {payload.priority}
Timestamp: {payload.timestamp or datetime.now().isoformat()}
Source: {payload.source_system or 'Unknown'}

DATA:
"""
        # Format the ERP data dictionary
        for key, value in payload.data.items():
            # Handle nested dictionaries and lists
            if isinstance(value, dict):
                erp_text += f"  {key}:\n"
                for sub_key, sub_value in value.items():
                    erp_text += f"    {sub_key}: {sub_value}\n"
            elif isinstance(value, list):
                erp_text += f"  {key}: {', '.join(str(v) for v in value)}\n"
            else:
                erp_text += f"  {key}: {value}\n"

        return erp_text

    @staticmethod
    def validate_webhook_signature(signature: str, payload: str, secret: str) -> bool:
        """Validate ERP webhook signature for security.

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

    @staticmethod
    def get_record_priority(record_type: str, data: dict) -> str:
        """Determine priority of ERP record based on type and data.

        Args:
            record_type: Type of ERP record
            data: ERP record data

        Returns:
            Priority level (HIGH, NORMAL, LOW)
        """
        # High priority for large orders, invoices, or critical shipments
        if record_type in ["invoice", "payment"]:
            return "HIGH"

        if record_type == "purchase_order":
            amount = data.get("total_amount", 0)
            if isinstance(amount, (int, float)) and amount > 10000:
                return "HIGH"

        if record_type == "shipment":
            status = data.get("status", "").upper()
            if status in ["DELAYED", "CANCELLED"]:
                return "HIGH"

        return "NORMAL"

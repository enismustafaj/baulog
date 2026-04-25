"""
Webhook Configuration Examples

This file contains setup and configuration examples for integrating
Baulog webhooks with email, Slack, and ERP systems.
"""

# ============================================================================
# EMAIL WEBHOOK SETUP
# ============================================================================
# Email webhooks can be configured with various email providers
#
# 1. MAILGUN INTEGRATION
# =====================
# 1. Create a Mailgun account (https://www.mailgun.com)
# 2. In Mailgun dashboard, go to Webhooks
# 3. Add webhook URL: https://your-domain.com:8000/webhooks/email
# 4. Select events: "Delivered", "Failed", "Bounced"
# 5. Mailgun will POST JSON with email data
#
# Example Mailgun webhook payload:
mailgun_example = {
    "signature": {
        "timestamp": "1234567890",
        "token": "abcdef123456",
        "signature": "hash_signature",
    },
    "event-data": {
        "timestamp": 1234567890.123,
        "type": "delivered",
        "id": "abc123",
        "log-level": "info",
        "message": {
            "headers": {
                "to": ["recipient@example.com"],
                "from": ["sender@example.com"],
                "subject": "Purchase Order Request",
            },
            "attachments": [],
            "size": 1234,
        },
        "recipient": "recipient@example.com",
        "id": "msg123",
    },
}

# 2. SENDGRID INTEGRATION
# =======================
# 1. Create a SendGrid account (https://sendgrid.com)
# 2. Go to Settings > Mail Send > Event Webhook
# 3. Set webhook URL: https://your-domain.com:8000/webhooks/email
# 4. Select events: "Delivered", "Bounce", "Click"
# 5. SendGrid will POST JSON with email data
#
# Example SendGrid webhook payload:
sendgrid_example = {
    "email": "sender@example.com",
    "timestamp": 1234567890,
    "smtpid": "<abc123@sendgrid.net>",
    "event": "delivered",
    "category": ["order", "urgent"],
    "sg_event_id": "msg-sg123",
    "sg_message_id": "msg-sg123.sendgrid.net",
    "response": "250 2.0.0 OK",
    "attempt": 1,
    "ip": "192.168.1.1",
    "useragent": "Mozilla/5.0",
    "urloffset": 0,
    "url": "https://example.com",
}

# 3. CUSTOM EMAIL SYSTEM
# =======================
# For custom email systems, POST to /webhooks/email with this format:
custom_email_payload = {
    "sender": "sender@example.com",
    "recipients": ["recipient1@example.com", "recipient2@example.com"],
    "subject": "Purchase Order #PO-2024-001",
    "body": """
Dear Sales Team,

We would like to place an order for the following:
- Product A: 100 units @ $50 per unit = $5,000
- Product B: 50 units @ $100 per unit = $5,000

Total: $10,000
Delivery Date: 2024-05-15

Please confirm availability and delivery timeline.

Best regards,
John Smith
Procurement Manager
    """,
    "message_id": "msg_12345_unique",
    "timestamp": "2024-04-25T10:30:00Z",
    "cc": ["manager@example.com"],
    "attachments": ["po_details.pdf", "budget_approval.docx"],
}


# ============================================================================
# SLACK WEBHOOK SETUP
# ============================================================================
# 1. CREATE A SLACK APP
# =======================
# 1. Go to https://api.slack.com/apps
# 2. Click "Create New App" > "From scratch"
# 3. Name: "Baulog Relevancy Agent"
# 4. Select workspace
#
# 2. CONFIGURE EVENT SUBSCRIPTIONS
# =================================
# 1. In app settings, go to "Event Subscriptions"
# 2. Toggle "Enable Events" ON
# 3. Set Request URL: https://your-domain.com:8000/webhooks/slack
# 4. Slack will send a verification challenge
# 5. Subscribe to these bot events:
#    - message.channels
#    - message.groups
#    - message.im
#    - message.mpim
# 6. Subscribe to these app events (optional):
#    - file_created
#    - file_shared
#    - app_mention
#
# 3. CONFIGURE OAUTH & PERMISSIONS
# ==================================
# 1. Go to "OAuth & Permissions"
# 2. Copy "Bot User OAuth Token" (save for reference)
# 3. Under "Scopes", add these bot token scopes:
#    - chat:write
#    - channels:read
#    - groups:read
#    - im:read
#    - users:read
#    - files:read
#
# Example Slack URL verification challenge:
slack_url_verification = {
    "token": "Xmx3tPPLSmcq7R5SZkAQO4jK",
    "challenge": "3eZbrw1aBrm2K0Oo7YPvAq",
    "type": "url_verification",
}

# Example Slack message event:
slack_message_event = {
    "token": "Xmx3tPPLSmcq7R5SZkAQO4jK",
    "team_id": "T024BE91L",
    "enterprise_id": None,
    "api_app_id": "A0KRQLBWH",
    "event": {
        "type": "message",
        "user": "U2147483697",
        "text": "We need to expedite the shipment due to unexpected production delays. Client is expecting delivery by Friday.",
        "ts": "1234567890.123456",
        "thread_ts": None,
        "channel": "C2147483705",
        "event_ts": "1234567890.123456",
    },
    "type": "event_callback",
    "event_id": "Ev0KRQLBJR",
    "event_time": 1234567890,
}

# Example Slack message with files:
slack_message_with_files = {
    "token": "Xmx3tPPLSmcq7R5SZkAQO4jK",
    "team_id": "T024BE91L",
    "api_app_id": "A0KRQLBWH",
    "event": {
        "type": "message",
        "user": "U2147483697",
        "text": "Updated product catalog and pricing",
        "ts": "1234567890.123456",
        "channel": "C2147483705",
        "event_ts": "1234567890.123456",
        "files": [
            {
                "id": "F024BE91L",
                "created": 1234567890,
                "timestamp": 1234567890,
                "name": "product_catalog_2024.xlsx",
                "title": "Product Catalog 2024",
                "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "pretty_type": "Excel Spreadsheet",
                "user": "U2147483697",
                "editable": True,
                "size": 1024000,
                "is_external": False,
                "is_public": False,
                "is_starred": False,
                "public_url_shared": False,
                "display_as_bot": False,
                "username": "john.smith",
                "url_private": "https://files.slack.com/files-pri/...",
                "url_private_download": "https://files.slack.com/files-pri/...",
                "thumb_64": "https://files.slack.com/files-tmb/...",
                "thumb_80": "https://files.slack.com/files-tmb/...",
                "thumb_360": "https://files.slack.com/files-tmb/...",
                "thumb_360_gif": None,
                "thumb_480": "https://files.slack.com/files-tmb/...",
                "thumb_720": "https://files.slack.com/files-tmb/...",
                "thumb_960": "https://files.slack.com/files-tmb/...",
                "thumb_1024": "https://files.slack.com/files-tmb/...",
                "original_w": 1200,
                "original_h": 800,
                "thumb_tiny": "AwAAA...",
                "has_rich_preview": True,
            }
        ],
    },
    "type": "event_callback",
    "event_id": "Ev0KRQLBJR",
    "event_time": 1234567890,
}


# ============================================================================
# ERP WEBHOOK SETUP
# ============================================================================
# ERP systems vary, but most support HTTP webhooks or APIs
#
# 1. SAP INTEGRATION
# ===================
# Setup:
# 1. In SAP, create an Outbound Process Integration (OPI) scenario
# 2. Configure Business Event as trigger
# 3. Set receiver URL: https://your-domain.com:8000/webhooks/erp
# 4. Select events:
#    - Purchase Order Created/Changed
#    - Invoice Received
#    - Shipment Created
#    - Payment Made
#
# Example SAP PO webhook:
sap_po_example = {
    "record_type": "purchase_order",
    "record_id": "4500001234",
    "system": "SAP",
    "source_system": "SAP_ERP_PROD",
    "priority": "HIGH",
    "timestamp": "2024-04-25T10:30:00Z",
    "data": {
        "vendor": "5000123",
        "vendor_name": "Tech Supplies Inc.",
        "creation_date": "2024-04-25",
        "document_date": "2024-04-25",
        "total_amount": 25000.00,
        "currency": "USD",
        "delivery_date": "2024-05-15",
        "status": "RELEASED",
        "items": [
            {
                "item_number": "00010",
                "material_id": "MAT-001-A",
                "material_description": "Server Hardware - High Performance",
                "quantity": 10,
                "unit": "PC",
                "unit_price": 2500.00,
                "amount": 25000.00,
            }
        ],
        "requested_delivery_date": "2024-05-15",
        "incoterms": "FCA",
        "payment_terms": "Net 30",
    },
}

# 2. ORACLE FUSION INTEGRATION
# ==============================
# Setup:
# 1. In Oracle Fusion, create a scheduled process
# 2. Configure REST API endpoint: /webhooks/erp
# 3. Set up subscriptions for:
#    - Requisition Events
#    - PO Events
#    - Invoice Events
#    - Receipt Events
#
# Example Oracle Invoice webhook:
oracle_invoice_example = {
    "record_type": "invoice",
    "record_id": "INV-2024-001234",
    "system": "Oracle Fusion",
    "source_system": "ORACLE_PROD",
    "priority": "HIGH",
    "timestamp": "2024-04-25T11:00:00Z",
    "data": {
        "vendor": "Supplier Inc.",
        "vendor_id": "50000123",
        "invoice_number": "INV-2024-001234",
        "invoice_date": "2024-04-25",
        "invoice_amount": 25000.00,
        "currency": "USD",
        "status": "RECEIVED",
        "invoice_type": "STANDARD",
        "po_number": "4500001234",
        "po_reference": "4500001234",
        "line_items": [
            {
                "line_number": 1,
                "description": "Server Hardware - High Performance",
                "quantity": 10,
                "unit_price": 2500.00,
                "amount": 25000.00,
            }
        ],
        "payment_terms": "Net 30",
        "due_date": "2024-05-25",
        "match_status": "MATCHED",
    },
}

# 3. NETSUITE INTEGRATION
# ========================
# Setup:
# 1. In NetSuite, create a User Event script or Scheduled script
# 2. Configure outbound call to: https://your-domain.com:8000/webhooks/erp
# 3. Trigger on events: Create, Update, Delete for Purchase Orders and Bills
#
# Example NetSuite PO webhook:
netsuite_po_example = {
    "record_type": "purchase_order",
    "record_id": "12345",
    "system": "NetSuite",
    "source_system": "NS_PROD",
    "priority": "NORMAL",
    "timestamp": "2024-04-25T10:30:00Z",
    "data": {
        "entity": "Supplier Inc.",
        "entity_id": "5000",
        "tranid": "PO-2024-001",
        "trandate": "2024-04-25",
        "total": 15000.00,
        "currency": "USD",
        "status": "Pending Approval",
        "expectedreceiptdate": "2024-05-10",
        "items": [
            {
                "item": "Product A",
                "itemid": "MAT-001",
                "quantity": 100,
                "rate": 150.00,
                "amount": 15000.00,
            }
        ],
    },
}

# 4. CUSTOM ERP SYSTEM
# =====================
# For any ERP system, POST to /webhooks/erp with this format:
custom_erp_payload = {
    "record_type": "purchase_order",  # purchase_order, invoice, shipment, payment, etc.
    "record_id": "PO-2024-001",
    "system": "Custom ERP",
    "source_system": "ERP_PRODUCTION",
    "priority": "HIGH",  # HIGH, NORMAL, LOW
    "timestamp": "2024-04-25T10:30:00Z",
    "data": {
        "vendor": "Supplier Inc.",
        "vendor_id": "V-12345",
        "total_amount": 25000.00,
        "currency": "USD",
        "items": [
            {
                "item_id": "I-001",
                "description": "Product Name",
                "quantity": 10,
                "unit_price": 2500.00,
            }
        ],
        "delivery_date": "2024-05-15",
        "status": "OPEN",
        # Add any custom fields specific to your ERP
    },
}


# ============================================================================
# TESTING WEBHOOKS LOCALLY
# ============================================================================
# Use these Python examples to test webhooks locally
#
# 1. INSTALL ngrok FOR TUNNELING
# ================================
# brew install ngrok
# ngrok http 8000
# This creates a public URL like: https://abc123def.ngrok.io
#
# 2. TEST EMAIL WEBHOOK
# =======================
import requests
import json

def test_email_webhook():
    """Test email webhook locally"""
    url = "http://localhost:8000/webhooks/email"
    payload = {
        "sender": "customer@example.com",
        "recipients": ["sales@yourcompany.com"],
        "subject": "Purchase Order #PO-2024-001",
        "body": "We would like to order 100 units at $50 per unit. Total: $5,000. Delivery needed by May 15.",
        "message_id": "msg_test_12345",
        "timestamp": "2024-04-25T10:30:00Z",
    }
    response = requests.post(url, json=payload)
    print(f"Email Webhook Response: {response.status_code}")
    print(json.dumps(response.json(), indent=2))

# 3. TEST SLACK WEBHOOK
# =======================
def test_slack_webhook():
    """Test Slack webhook locally"""
    url = "http://localhost:8000/webhooks/slack"
    payload = {
        "type": "event_callback",
        "event": {
            "type": "message",
            "channel": "C123456",
            "user": "U789012",
            "text": "We need to expedite this order due to production delays. Can we get it by Friday?",
            "timestamp": "1234567890.123456",
        },
        "team_id": "T123456",
        "api_app_id": "A123456",
        "event_id": "Ev123456",
        "event_time": 1234567890,
    }
    response = requests.post(url, json=payload)
    print(f"Slack Webhook Response: {response.status_code}")
    print(json.dumps(response.json(), indent=2))

# 4. TEST ERP WEBHOOK
# ====================
def test_erp_webhook():
    """Test ERP webhook locally"""
    url = "http://localhost:8000/webhooks/erp"
    payload = {
        "record_type": "purchase_order",
        "record_id": "PO-2024-001",
        "system": "SAP",
        "priority": "HIGH",
        "timestamp": "2024-04-25T10:30:00Z",
        "data": {
            "vendor": "Tech Supplies Inc.",
            "total_amount": 15000.00,
            "currency": "USD",
            "items": [
                {
                    "material_id": "MAT-001",
                    "description": "Server Hardware",
                    "quantity": 10,
                    "unit_price": 1500.00,
                }
            ],
            "delivery_date": "2024-05-15",
            "status": "RELEASED",
        },
    }
    response = requests.post(url, json=payload)
    print(f"ERP Webhook Response: {response.status_code}")
    print(json.dumps(response.json(), indent=2))


if __name__ == "__main__":
    print("Webhook Configuration Examples")
    print("=" * 80)
    print("\nRun these test functions with:")
    print("  python -c 'from examples.webhook_examples import test_email_webhook; test_email_webhook()'")
    print("  python -c 'from examples.webhook_examples import test_slack_webhook; test_slack_webhook()'")
    print("  python -c 'from examples.webhook_examples import test_erp_webhook; test_erp_webhook()'")

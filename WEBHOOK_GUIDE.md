# Webhook Integration Guide

This guide provides step-by-step instructions for setting up webhooks with Baulog to receive data from email, Slack, and ERP systems.

## Quick Start

All webhooks are available at:
- **Email**: `POST /webhooks/email`
- **Slack**: `POST /webhooks/slack`
- **ERP**: `POST /webhooks/erp`

## Email Webhook Setup

### Option 1: Mailgun

1. **Create Mailgun Account**
   - Visit https://www.mailgun.com
   - Sign up and verify your domain

2. **Configure Webhook**
   - In Mailgun dashboard, go to **Webhooks**
   - Click **Add Webhook**
   - Select events: "Delivered", "Failed", "Bounced"
   - Set webhook URL to: `https://your-domain.com:8000/webhooks/email`

3. **Test**
   ```bash
   curl -X POST "http://localhost:8000/webhooks/email" \
     -H "Content-Type: application/json" \
     -d '{
       "sender": "test@example.com",
       "recipients": ["recipient@example.com"],
       "subject": "Test Email",
       "body": "This is a test message",
       "message_id": "msg_test_001"
     }'
   ```

### Option 2: SendGrid

1. **Create SendGrid Account**
   - Visit https://sendgrid.com
   - Sign up and create an API key

2. **Configure Event Webhook**
   - Go to **Settings** > **Mail Send** > **Event Webhook**
   - Set webhook URL to: `https://your-domain.com:8000/webhooks/email`
   - Subscribe to: "Delivered", "Bounce", "Click"

3. **Test**
   - Send test email through SendGrid
   - Check webhook response

### Option 3: Custom Email System

For any email system, POST JSON to `/webhooks/email`:

```json
{
  "sender": "john@company.com",
  "recipients": ["sales@company.com"],
  "subject": "Purchase Order #PO-2024-001",
  "body": "We need 100 units of Product X at $50 per unit. Delivery by May 15.",
  "message_id": "msg_12345",
  "timestamp": "2024-04-25T10:30:00Z",
  "cc": ["manager@company.com"],
  "attachments": ["po_details.pdf"]
}
```

## Slack Webhook Setup

### Step 1: Create Slack App

1. Go to https://api.slack.com/apps
2. Click **Create New App** > **From scratch**
3. Name: "Baulog Relevancy Agent"
4. Select your workspace
5. Click **Create App**

### Step 2: Enable Event Subscriptions

1. In app settings, click **Event Subscriptions**
2. Toggle **Enable Events** to ON
3. In **Request URL**, enter: `https://your-domain.com:8000/webhooks/slack`
4. Slack will send a verification challenge - Baulog automatically responds
5. Under **Subscribe to bot events**, add:
   - `message.channels`
   - `message.groups`
   - `message.im`
   - `message.mpim`
6. Click **Save Changes**

### Step 3: OAuth & Permissions (Optional)

1. Go to **OAuth & Permissions**
2. Under **Scopes**, add bot token scopes:
   - `chat:write` (if you want to send responses)
   - `channels:read`
   - `users:read`
3. Copy **Bot User OAuth Token** for reference

### Step 4: Install App

1. Go to **Install App**
2. Click **Install to Workspace**
3. Authorize the app

### Step 5: Test

```bash
# Send a message in Slack that the app can read
# Or test directly:

curl -X POST "http://localhost:8000/webhooks/slack" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "event_callback",
    "event": {
      "type": "message",
      "channel": "C123456",
      "user": "U789012",
      "text": "We need to expedite the shipment due to production delays",
      "timestamp": "1234567890.123456"
    },
    "team_id": "T123456",
    "event_id": "Ev123456",
    "event_time": 1234567890
  }'
```

## ERP Webhook Setup

### SAP Integration

1. **Enable Outbound Process Integration**
   - In SAP, go to **Transaction SXPRA**
   - Create new outbound process

2. **Configure Business Event**
   - Select event triggers:
     - `PURCHASEORDER_CREATED`
     - `PURCHASEORDER_CHANGED`
     - `INVOICE_RECEIVED`
     - `SHIPMENT_CREATED`

3. **Set Receiver**
   - Type: HTTP
   - URL: `https://your-domain.com:8000/webhooks/erp`
   - Authentication: Basic or Custom Header

4. **Test**
   ```bash
   curl -X POST "http://localhost:8000/webhooks/erp" \
     -H "Content-Type: application/json" \
     -d '{
       "record_type": "purchase_order",
       "record_id": "4500001234",
       "system": "SAP",
       "priority": "HIGH",
       "timestamp": "2024-04-25T10:30:00Z",
       "data": {
         "vendor": "Tech Supplies Inc.",
         "total_amount": 25000,
         "currency": "USD",
         "delivery_date": "2024-05-15",
         "status": "RELEASED"
       }
     }'
   ```

### Oracle Fusion Integration

1. **Create REST API Integration**
   - Go to **Setup** > **Integration** > **REST APIs**
   - Create new API definition

2. **Configure Subscriptions**
   - Subscribe to events:
     - Requisition Created/Updated
     - PO Created/Updated
     - Invoice Received/Updated

3. **Set Webhook URL**
   - `https://your-domain.com:8000/webhooks/erp`

### NetSuite Integration

1. **Create User Event Script**
   - Go to **Customization** > **Scripting** > **Scripts** > **New**
   - Type: **User Event**

2. **Configure Script**
   ```javascript
   function beforeLoad(context) {}
   function beforeSubmit(context) {}
   function afterSubmit(context) {
       // Send webhook to Baulog
       var url = "https://your-domain.com:8000/webhooks/erp";
       var payload = {
           record_type: context.type,
           record_id: context.newRecord.id,
           system: "NetSuite",
           data: {
               // Map NetSuite fields to webhook format
           }
       };
       // Make HTTP call
   }
   ```

### Generic ERP System

For any ERP system:

```json
{
  "record_type": "purchase_order",
  "record_id": "PO-2024-001",
  "system": "ERP_System_Name",
  "priority": "HIGH",
  "timestamp": "2024-04-25T10:30:00Z",
  "data": {
    "vendor": "Supplier Inc.",
    "total_amount": 25000,
    "currency": "USD",
    "items": [
      {
        "item_id": "I-001",
        "description": "Product Name",
        "quantity": 10,
        "unit_price": 2500
      }
    ],
    "delivery_date": "2024-05-15",
    "status": "OPEN"
  }
}
```

## Local Testing with ngrok

For testing webhooks locally before deploying:

1. **Install ngrok**
   ```bash
   brew install ngrok  # macOS
   # or download from https://ngrok.com
   ```

2. **Start ngrok**
   ```bash
   ngrok http 8000
   ```
   This creates a public URL: `https://abc123def.ngrok.io`

3. **Configure webhooks**
   - Use ngrok URL instead of localhost
   - Example: `https://abc123def.ngrok.io/webhooks/email`

4. **Stop ngrok**
   ```bash
   # Press Ctrl+C in the ngrok terminal
   ```

## Webhook Security

### Email & ERP Webhook Validation

Configure HMAC signatures for security:

1. **Set webhook secret in `.env`**
   ```env
   EMAIL_WEBHOOK_SECRET=your_secret_key_here
   ERP_WEBHOOK_SECRET=your_secret_key_here
   ```

2. **In your webhook sender**, compute HMAC signature:
   ```python
   import hmac
   import hashlib
   
   secret = "your_secret_key_here"
   payload = "raw_request_body"
   signature = hmac.new(
       secret.encode(),
       payload.encode(),
       hashlib.sha256
   ).hexdigest()
   ```

3. **Include signature in headers**
   ```bash
   curl -X POST "http://localhost:8000/webhooks/email" \
     -H "Content-Type: application/json" \
     -H "X-Signature: your_computed_signature" \
     -H "X-Secret: webhook_identifier" \
     -d '{...}'
   ```

### Slack Webhook Validation

Slack automatically validates signatures (included in implementation):
- Timestamp validation (within 5 minutes)
- HMAC-SHA256 signature verification

## Response Format

All webhooks return:

```json
{
  "status": "processed",
  "message": "Description of what was processed",
  "data_id": "unique_identifier",
  "relevant": true,
  "assessment": "RELEVANT - Detailed assessment from agent...",
  "processed_at": "2024-04-25T10:30:05Z"
}
```

## Error Handling

**Missing agent:**
```json
{
  "detail": "Relevancy agent is not initialized. Please set GOOGLE_API_KEY environment variable."
}
```

**Invalid payload:**
```json
{
  "detail": "Error evaluating data: validation error..."
}
```

## Monitoring Webhooks

To monitor webhook processing:

1. **Check server logs**
   ```bash
   python main.py
   # Look for processing logs
   ```

2. **Enable debug mode** (optional)
   ```bash
   DEBUG=true python main.py
   ```

3. **Test health endpoint**
   ```bash
   curl http://localhost:8000/health
   ```

## Troubleshooting

### Slack URL Verification Failed
- Ensure server is accessible at configured URL
- Check ngrok is running
- Verify firewall allows inbound traffic

### Email Webhook Not Triggered
- Verify webhook URL in email provider settings
- Check network connectivity
- Test with curl command first

### ERP Data Not Processing
- Verify JSON format matches expected schema
- Check `record_type` is valid
- Ensure `timestamp` is ISO 8601 format

### Agent Not Processing
- Set `GOOGLE_API_KEY` in `.env`
- Run `pip install -e .` to update dependencies
- Check `/health` endpoint shows agent as "ready"

## Advanced Configuration

### Routing by Data Type

Customize agent behavior based on source:

```python
# In main.py
if payload.record_type == "invoice":
    # Use specialized invoice assessment
    result = invoice_agent.evaluate(erp_text)
else:
    # Use general agent
    result = relevancy_agent.evaluate(erp_text)
```

### Custom Evaluation Prompts

Modify agent system prompts in [agents/relevancy_agent.py](../agents/relevancy_agent.py)

### Webhook Queuing

For high-volume webhooks, add queue handling:

```bash
pip install celery redis
```

Then implement async processing.

## Support

For issues or questions:
1. Check webhook_examples.py for reference implementations
2. Review README.md for overview
3. Check error logs from server output

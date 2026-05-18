# WhatsApp Order Management SaaS Bot

A multi-client WhatsApp bot for order management. One deployment serves multiple businesses.

## Project Structure

```
whatsapp-saas/
├── app.py              # Main webhook handler
├── logic.py            # Order management (Google Sheets)
├── whatsapp.py         # Message sending
├── sheets.py           # Google Sheets API
├── logger.py           # Conversation + error logging
├── config_loader.py    # Multi-client config management
├── requirements.txt
├── Procfile
├── .gitignore
└── clients/
    ├── sahil_processors.json       # Client 1 config
    └── punjab_bakery.json.example  # Example config
```

## Adding a New Client

1. Copy `clients/punjab_bakery.json.example` to `clients/your_client.json`
2. Fill in their details:
   - `phone_number_id` — from their Meta Developer Console
   - `access_token` — their WhatsApp API token
   - `verify_token` — any strong random string
   - `staff_numbers` — their staff WhatsApp numbers
   - `google_sheet_id` — their Google Sheet ID
   - `statuses` — their custom order statuses
3. Share the Google Sheet with your service account email
4. Push to GitHub — Render picks it up automatically

## Features (configurable per client)

| Feature | Description | Default |
|---|---|---|
| `expected_delivery` | Staff can set delivery date/time | ✅ On |
| `update_status` | Staff can update order status | ✅ On |
| `orders_by_date` | Filter orders by date | ✅ On |
| `existing_client` | Select existing client when creating order | ✅ On |
| `stale_orders_alert` | Alert staff for orders not updated in 6hrs | ✅ On |
| `late_delivery_alert` | Notify customer when delivery time passed | ✅ On |
| `customer_tracking` | Customer can track their orders | ✅ On |

## Environment Variables (Render)

```
GOOGLE_CREDENTIALS = { entire JSON content }
```

Note: Client-specific tokens (ACCESS_TOKEN, PHONE_NUMBER_ID) are stored in client JSON files, not environment variables.

## Google Sheets Structure (per client)

Each client's spreadsheet has 3 tabs:
- **Orders** — all order data
- **Conversations** — all messages (auto-deleted after 30 days)
- **Errors** — all errors (auto-deleted after 30 days)

## Webhook URL

```
https://your-render-url.onrender.com/webhook
```

All clients share the same webhook URL. The bot identifies clients by `phone_number_id` from the incoming webhook payload.

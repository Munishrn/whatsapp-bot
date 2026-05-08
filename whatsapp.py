import requests
from config import ACCESS_TOKEN, PHONE_NUMBER_ID, API_VERSION


def _post(data, context="message"):
    url = f"https://graph.facebook.com/{API_VERSION}/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    try:
        response = requests.post(url, headers=headers, json=data, timeout=10)
        if not response.ok:
            print(f"[WhatsApp API Error] {context}: {response.status_code} — {response.text}")
        return response
    except requests.exceptions.RequestException as e:
        print(f"[WhatsApp Request Failed] {context}: {e}")
        return None


def send_staff_menu(phone):
    data = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": "🖨️ Welcome to Sahil Processors Staff Panel\nSelect an action to manage your orders."
            },
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "create_order", "title": "Create Order"}},
                    {"type": "reply", "reply": {"id": "update_order", "title": "Update Order"}},
                    {"type": "reply", "reply": {"id": "view_orders",  "title": "View Orders"}},
                ]
            }
        }
    }
    _post(data, context=f"send_staff_menu to {phone}")


def send_customer_menu(phone):
    data = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": "👋 Welcome to Sahil Processors!\nWe're here to help you track and manage your printing orders. How can we assist you today?"
            },
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "check_status", "title": "Track Order"}},
                    {"type": "reply", "reply": {"id": "view_by_date", "title": "Orders by Date"}},
                ]
            }
        }
    }
    _post(data, context=f"send_customer_menu to {phone}")


def send_back_button(phone, text):
    data = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": text},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "back_to_menu", "title": "⬅️ Back"}}
                ]
            }
        }
    }
    _post(data, context=f"send_back_button to {phone}")


def send_view_options(phone):
    data = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": "🔍 View Orders\nSearch by Order ID for a specific order, or filter by date."
            },
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "view_order",   "title": "By Order ID"}},
                    {"type": "reply", "reply": {"id": "view_by_date", "title": "By Date"}},
                    {"type": "reply", "reply": {"id": "back_to_menu", "title": "⬅️ Back"}},
                ]
            }
        }
    }
    _post(data, context=f"send_view_options to {phone}")


def send_update_options(phone):
    """Ask staff what to update — Status, Delivery Time, or Both."""
    data = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": "✏️ What would you like to update?"
            },
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "update_status_only",   "title": "Status Only"}},
                    {"type": "reply", "reply": {"id": "update_delivery_only", "title": "Delivery Time"}},
                    {"type": "reply", "reply": {"id": "update_both",          "title": "Both"}},
                ]
            }
        }
    }
    _post(data, context=f"send_update_options to {phone}")


def send_create_order_type(phone):
    data = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": "📋 Creating a New Order\nIs this client new or have they ordered before?"
            },
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "client_new",      "title": "🆕 New Client"}},
                    {"type": "reply", "reply": {"id": "client_existing", "title": "👥 Existing Client"}},
                    {"type": "reply", "reply": {"id": "back_to_menu",    "title": "⬅️ Back"}},
                ]
            }
        }
    }
    _post(data, context=f"send_create_order_type to {phone}")


def send_existing_clients_list(phone, clients):
    if not clients:
        send_text(phone, "❌ No existing clients found. Please create a new client.")
        return

    sections = []
    chunk_size = 10
    for i in range(0, len(clients), chunk_size):
        chunk = clients[i:i + chunk_size]
        sections.append({
            "title": f"Clients {i+1}–{min(i+chunk_size, len(clients))}",
            "rows": [
                {
                    "id": f"existing_client_{idx}_{c['phone']}",
                    "title": c["name"][:24],
                    "description": c["phone"]
                }
                for idx, c in enumerate(chunk)
            ]
        })

    data = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {
                "text": f"👥 Select an existing client ({len(clients)} found):"
            },
            "action": {
                "button": "Choose Client",
                "sections": sections
            }
        }
    }
    _post(data, context=f"send_existing_clients_list to {phone}")



def send_delivery_date_picker(phone):
    """Show quick date options for delivery date selection."""
    from datetime import datetime, timedelta
    today    = datetime.now()
    tomorrow = today + timedelta(days=1)
    day_after = today + timedelta(days=2)

    data = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {
                "text": "📅 Select Expected Delivery Date:"
            },
            "action": {
                "button": "Choose Date",
                "sections": [
                    {
                        "title": "Quick Select",
                        "rows": [
                            {"id": f"del_date_{today.strftime('%d-%m-%Y')}",     "title": f"Today ({today.strftime('%d %b')})"},
                            {"id": f"del_date_{tomorrow.strftime('%d-%m-%Y')}",  "title": f"Tomorrow ({tomorrow.strftime('%d %b')})"},
                            {"id": f"del_date_{day_after.strftime('%d-%m-%Y')}", "title": f"Day After ({day_after.strftime('%d %b')})"},
                            {"id": "del_date_custom", "title": "📝 Enter Custom Date"},
                        ]
                    }
                ]
            }
        }
    }
    _post(data, context=f"send_delivery_date_picker to {phone}")


def send_delivery_time_picker(phone, selected_date):
    """Show time slots — filters out past times if selected date is today."""
    from datetime import datetime

    all_slots = [
        ("09:00", "9:00 AM"),
        ("11:00", "11:00 AM"),
        ("13:00", "1:00 PM"),
        ("15:00", "3:00 PM"),
        ("17:00", "5:00 PM"),
        ("19:00", "7:00 PM"),
    ]

    now = datetime.now()
    today_str = now.strftime("%d-%m-%Y")
    is_today = selected_date == today_str

    # Filter out past times if today is selected
    available = []
    for time_24, label in all_slots:
        if is_today:
            slot_dt = datetime.strptime(f"{selected_date} {time_24}", "%d-%m-%Y %H:%M")
            if slot_dt <= now:
                continue  # Skip past times
        available.append({"id": f"del_time_{time_24}", "title": label})

    # Always add custom option
    available.append({"id": "del_time_custom", "title": "📝 Enter Custom Time"})

    if len(available) <= 1:
        # All slots passed — only custom remains
        rows = available
    else:
        rows = available

    data = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {
                "text": f"🕐 Select Expected Delivery Time for {selected_date}:"
            },
            "action": {
                "button": "Choose Time",
                "sections": [
                    {
                        "title": "Available Time Slots",
                        "rows": rows
                    }
                ]
            }
        }
    }
    _post(data, context=f"send_delivery_time_picker to {phone}")

def send_date_options(phone):
    """Show date options for order filtering — quick select like delivery date picker."""
    from datetime import datetime, timedelta
    today     = datetime.now()
    yesterday = today - timedelta(days=1)
    day_before = today - timedelta(days=2)

    data = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {
                "text": "📅 View Orders by Date\nSelect a date to view orders:"
            },
            "action": {
                "button": "Choose Date",
                "sections": [
                    {
                        "title": "Quick Select",
                        "rows": [
                            {"id": f"filter_date_{today.strftime('%d-%m-%Y')}",      "title": f"Today ({today.strftime('%d %b')})"},
                            {"id": f"filter_date_{yesterday.strftime('%d-%m-%Y')}",  "title": f"Yesterday ({yesterday.strftime('%d %b')})"},
                            {"id": f"filter_date_{day_before.strftime('%d-%m-%Y')}", "title": f"Day Before ({day_before.strftime('%d %b')})"},
                            {"id": "filter_date_custom", "title": "📝 Enter Custom Date"},
                        ]
                    }
                ]
            }
        }
    }
    _post(data, context=f"send_date_options to {phone}")


def send_status_list(phone, text):
    data = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": text},
            "action": {
                "button": "Select Status",
                "sections": [
                    {
                        "title": "Order Status",
                        "rows": [
                            {"id": "status_design",    "title": "Design Making"},
                            {"id": "status_plate",     "title": "Plate Making"},
                            {"id": "status_printing",  "title": "Offset Printing"},
                            {"id": "status_ready",     "title": "Ready to be picked"},
                            {"id": "status_delivery",  "title": "Out for delivery"},
                            {"id": "status_cancelled", "title": "Cancelled"},
                        ]
                    }
                ]
            }
        }
    }
    _post(data, context=f"send_status_list to {phone}")


def send_text(phone, msg):
    max_len = 4000
    if len(msg) <= max_len:
        data = {
            "messaging_product": "whatsapp",
            "to": phone,
            "text": {"body": msg}
        }
        _post(data, context=f"send_text to {phone}")
    else:
        chunks = [msg[i:i+max_len] for i in range(0, len(msg), max_len)]
        for i, chunk in enumerate(chunks):
            data = {
                "messaging_product": "whatsapp",
                "to": phone,
                "text": {"body": chunk}
            }
            _post(data, context=f"send_text chunk {i+1} to {phone}")

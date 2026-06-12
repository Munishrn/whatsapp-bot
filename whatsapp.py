"""
whatsapp.py — Send WhatsApp messages using client's own credentials.
All functions accept `cfg` (client config dict).
"""

import requests
from datetime import datetime, timedelta


def _safe_sections(sections, max_rows=10):
    """
    Ensure no section exceeds WhatsApp 10 row limit.
    Splits oversized sections into multiple sections automatically.
    """
    safe = []
    for section in sections:
        rows = section.get("rows", [])
        if not rows:
            continue
        if len(rows) <= max_rows:
            safe.append(section)
        else:
            for i in range(0, len(rows), max_rows):
                chunk = rows[i:i+max_rows]
                label = section["title"] if i == 0 else f"{section['title']} (cont.)"
                safe.append({"title": label, "rows": chunk})
    # WhatsApp also limits total sections to 10
    return safe[:10]


def _post(cfg, data, context="message"):
    """Send message using client's own access token and phone number ID."""
    token    = cfg["access_token"]
    pid      = cfg["phone_number_id"]
    version  = cfg.get("api_version", "v19.0")
    url      = f"https://graph.facebook.com/{version}/{pid}/messages"
    headers  = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=10)
        if not resp.ok:
            print(f"[WhatsApp Error] {context}: {resp.status_code} — {resp.text}")
        return resp
    except requests.exceptions.RequestException as e:
        print(f"[WhatsApp Failed] {context}: {e}")
        return None


def send_text(cfg, phone, msg):
    max_len = 4000
    if len(msg) <= max_len:
        _post(cfg, {
            "messaging_product": "whatsapp",
            "to":   phone,
            "type": "text",
            "text": {"body": msg}
        }, context=f"send_text to {phone}")
    else:
        chunks = [msg[i:i+max_len] for i in range(0, len(msg), max_len)]
        for i, chunk in enumerate(chunks):
            _post(cfg, {
                "messaging_product": "whatsapp",
                "to":   phone,
                "type": "text",
                "text": {"body": chunk}
            }, context=f"send_text chunk {i+1} to {phone}")


def send_back_button(cfg, phone, text):
    _post(cfg, {
        "messaging_product": "whatsapp",
        "to":   phone,
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
    }, context=f"send_back_button to {phone}")


def send_staff_menu(cfg, phone):
    welcome = cfg.get("welcome_staff", f"👨‍💼 Welcome to {cfg.get('business_name')} Staff Panel\nSelect an action.")
    # Row 1 — main actions
    _post(cfg, {
        "messaging_product": "whatsapp",
        "to":   phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": welcome},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "create_order",  "title": "Create Order"}},
                    {"type": "reply", "reply": {"id": "update_order",  "title": "Update Order"}},
                    {"type": "reply", "reply": {"id": "view_orders",   "title": "View Orders"}},
                ]
            }
        }
    }, context=f"send_staff_menu row1 to {phone}")

    # Row 2 — quick actions
    _post(cfg, {
        "messaging_product": "whatsapp",
        "to":   phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": "📋 Quick Actions:"},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "todays_orders", "title": "Today's Orders"}},
                ]
            }
        }
    }, context=f"send_staff_menu row2 to {phone}")


def send_customer_menu(cfg, phone):
    welcome = cfg.get("welcome_customer", f"👋 Welcome to {cfg.get('business_name')}!\nHow can we help you?")
    _post(cfg, {
        "messaging_product": "whatsapp",
        "to":   phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": welcome},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "check_status", "title": "Track Order"}},
                    {"type": "reply", "reply": {"id": "view_by_date", "title": "Orders by Date"}},
                ]
            }
        }
    }, context=f"send_customer_menu to {phone}")


def send_status_list(cfg, phone, text):
    """Build status list dynamically from client config."""
    statuses = cfg.get("statuses", [])
    all_rows = [{"id": f"status_{i}", "title": s} for i, s in enumerate(statuses)]
    # ✅ WhatsApp max 10 rows per section
    sections = []
    chunk_size = 10
    for i in range(0, len(all_rows), chunk_size):
        chunk = all_rows[i:i+chunk_size]
        label = "Order Status" if i == 0 else f"More Statuses"
        sections.append({"title": label, "rows": chunk})

    _post(cfg, {
        "messaging_product": "whatsapp",
        "to":   phone,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": text},
            "action": {
                "button": "Select Status",
                "sections": _safe_sections(sections)
            }
        }
    }, context=f"send_status_list to {phone}")


def send_create_order_type(cfg, phone):
    _post(cfg, {
        "messaging_product": "whatsapp",
        "to":   phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": "📋 Creating a New Order\nIs this client new or have they ordered before?"},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "client_new",      "title": "🆕 New Client"}},
                    {"type": "reply", "reply": {"id": "client_existing", "title": "👥 Existing Client"}},
                    {"type": "reply", "reply": {"id": "back_to_menu",    "title": "⬅️ Back"}},
                ]
            }
        }
    }, context=f"send_create_order_type to {phone}")


def send_existing_clients_list(cfg, phone, clients):
    if not clients:
        send_text(cfg, phone, "❌ No existing clients found. Please create a new client.")
        return
    sections = []
    chunk_size = 10
    for i in range(0, len(clients), chunk_size):
        chunk = clients[i:i+chunk_size]
        sections.append({
            "title": f"Clients {i+1}–{min(i+chunk_size, len(clients))}",
            "rows": [
                {"id": f"existing_client_{j}_{c['phone']}", "title": c["name"][:24], "description": c["phone"]}
                for j, c in enumerate(chunk)
            ]
        })
    _post(cfg, {
        "messaging_product": "whatsapp",
        "to":   phone,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": f"👥 Select an existing client ({len(clients)} found):"},
            "action": {"button": "Choose Client", "sections": _safe_sections(sections)}
        }
    }, context=f"send_existing_clients_list to {phone}")


def send_update_options(cfg, phone):
    delivery_enabled = cfg.get("features", {}).get("expected_delivery", True)

    if delivery_enabled:
        buttons = [
            {"type": "reply", "reply": {"id": "update_status_only",   "title": "Status Only"}},
            {"type": "reply", "reply": {"id": "update_delivery_only", "title": "Delivery Time"}},
            {"type": "reply", "reply": {"id": "update_both",          "title": "Both"}},
        ]
    else:
        # ✅ Only show Status Only when expected_delivery is disabled
        buttons = [
            {"type": "reply", "reply": {"id": "update_status_only", "title": "Update Status"}},
            {"type": "reply", "reply": {"id": "back_to_menu",       "title": "⬅️ Back"}},
        ]

    _post(cfg, {
        "messaging_product": "whatsapp",
        "to":   phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": "✏️ What would you like to update?"},
            "action": {"buttons": buttons}
        }
    }, context=f"send_update_options to {phone}")


def send_view_options(cfg, phone):
    _post(cfg, {
        "messaging_product": "whatsapp",
        "to":   phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": "🔍 View Orders\nSearch by Order ID for a specific order, or filter by date."},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "view_order",   "title": "By Order ID"}},
                    {"type": "reply", "reply": {"id": "view_by_date", "title": "By Date"}},
                    {"type": "reply", "reply": {"id": "back_to_menu", "title": "⬅️ Back"}},
                ]
            }
        }
    }, context=f"send_view_options to {phone}")


def send_date_options(cfg, phone):
    today      = datetime.now()
    yesterday  = today - timedelta(days=1)
    day_before = today - timedelta(days=2)
    _post(cfg, {
        "messaging_product": "whatsapp",
        "to":   phone,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": "📅 View Orders by Date\nSelect a date to view orders:"},
            "action": {
                "button": "Choose Date",
                "sections": _safe_sections([{
                    "title": "Quick Select",
                    "rows": [
                        {"id": f"filter_date_{today.strftime('%d-%m-%Y')}",      "title": f"Today ({today.strftime('%d %b')})"},
                        {"id": f"filter_date_{yesterday.strftime('%d-%m-%Y')}",  "title": f"Yesterday ({yesterday.strftime('%d %b')})"},
                        {"id": f"filter_date_{day_before.strftime('%d-%m-%Y')}", "title": f"Day Before ({day_before.strftime('%d %b')})"},
                        {"id": "filter_date_custom", "title": "📝 Enter Custom Date"},
                    ]
                }])
            }
        }
    }, context=f"send_date_options to {phone}")


def send_delivery_date_picker(cfg, phone):
    today     = datetime.now()
    tomorrow  = today + timedelta(days=1)
    day_after = today + timedelta(days=2)
    _post(cfg, {
        "messaging_product": "whatsapp",
        "to":   phone,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": "📅 Select Expected Delivery Date:"},
            "action": {
                "button": "Choose Date",
                "sections": _safe_sections([{
                    "title": "Quick Select",
                    "rows": [
                        {"id": f"del_date_{today.strftime('%d-%m-%Y')}",     "title": f"Today ({today.strftime('%d %b')})"},
                        {"id": f"del_date_{tomorrow.strftime('%d-%m-%Y')}",  "title": f"Tomorrow ({tomorrow.strftime('%d %b')})"},
                        {"id": f"del_date_{day_after.strftime('%d-%m-%Y')}", "title": f"Day After ({day_after.strftime('%d %b')})"},
                        {"id": "del_date_custom", "title": "📝 Enter Custom Date"},
                    ]
                }])
            }
        }
    }, context=f"send_delivery_date_picker to {phone}")


def send_delivery_time_picker(cfg, phone, selected_date):
    now        = datetime.now()
    today_str  = now.strftime("%d-%m-%Y")
    is_today   = selected_date == today_str
    is_past    = False
    try:
        sel_dt  = datetime.strptime(selected_date, "%d-%m-%Y")
        is_past = sel_dt.date() < now.date()
    except Exception:
        pass

    # If selected date is in the past, only show custom option
    if is_past:
        sections = [{"title": "Options", "rows": [
            {"id": "del_time_custom", "title": "📝 Enter Custom Time"}
        ]}]
        _post(cfg, {
            "messaging_product": "whatsapp",
            "to":   phone,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": f"🕐 Select Delivery Time for {selected_date}:\n⚠️ This date is in the past. Please enter a custom time."},
                "action": {"button": "Choose Time", "sections": sections}
            }
        }, context=f"send_delivery_time_picker to {phone}")
        return

    # Fixed slots — max 9 per section + 1 custom = 10 total per section
    all_slots = [
        ("09:00", "9:00 AM"),
        ("10:00", "10:00 AM"),
        ("11:00", "11:00 AM"),
        ("12:00", "12:00 PM"),
        ("13:00", "1:00 PM"),
        ("14:00", "2:00 PM"),
        ("15:00", "3:00 PM"),
        ("16:00", "4:00 PM"),
        ("17:00", "5:00 PM"),
        ("18:00", "6:00 PM"),
        ("19:00", "7:00 PM"),
        ("20:00", "8:00 PM"),
    ]

    available = []
    for time_24, label in all_slots:
        if is_today:
            slot_dt = datetime.strptime(f"{selected_date} {time_24}", "%d-%m-%Y %H:%M")
            if slot_dt <= now:
                continue
        available.append({"id": f"del_time_{time_24}", "title": label})

    custom = {"id": "del_time_custom", "title": "📝 Enter Custom Time"}

    # ✅ Strictly cap at 9 slots per section, custom always in its own last section
    sections = []
    chunk_size = 9
    chunks = [available[i:i+chunk_size] for i in range(0, len(available), chunk_size)]
    labels = ["Morning / Afternoon", "Afternoon / Evening", "Evening", "Other"]

    for i, chunk in enumerate(chunks):
        label = labels[i] if i < len(labels) else f"Slots {i+1}"
        sections.append({"title": label, "rows": list(chunk)})  # list() to avoid mutation

    # Always add custom as last item in last section if room, else new section
    if sections and len(sections[-1]["rows"]) < 10:
        sections[-1]["rows"].append(custom)
    else:
        sections.append({"title": "Options", "rows": [custom]})

    if not sections:
        sections = [{"title": "Options", "rows": [custom]}]

    _post(cfg, {
        "messaging_product": "whatsapp",
        "to":   phone,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": f"🕐 Select Expected Delivery Time for {selected_date}:"},
            "action": {"button": "Choose Time", "sections": _safe_sections(sections)}
        }
    }, context=f"send_delivery_time_picker to {phone}")



def send_template_message(cfg, phone, template_name, variables):
    """
    Send a WhatsApp approved template message.
    variables: list of strings [var1, var2, var3...]
    """
    token   = cfg["access_token"]
    pid     = cfg["phone_number_id"]
    version = cfg.get("api_version", "v19.0")
    url     = f"https://graph.facebook.com/{version}/{pid}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    components = []
    if variables:
        components.append({
            "type": "body",
            "parameters": [
                {"type": "text", "text": str(v)} for v in variables
            ]
        })

    data = {
        "messaging_product": "whatsapp",
        "to":   phone,
        "type": "template",
        "template": {
            "name":     template_name,
            "language": {"code": "en"},
            "components": components
        }
    }

    try:
        resp = requests.post(url, headers=headers, json=data, timeout=10)
        if not resp.ok:
            print(f"[Template Error] {template_name} to {phone}: {resp.status_code} — {resp.text}")
        return resp
    except requests.exceptions.RequestException as e:
        print(f"[Template Failed] {template_name} to {phone}: {e}")
        return None


def send_plate_making_template(cfg, phone, customer_name, order_id, description):
    """
    Send order_status_plate template.
    Variables:
        {{1}} = customer name
        {{2}} = order ID
        {{3}} = product description
    """
    return send_template_message(
        cfg, phone,
        template_name="order_status_plate",
        variables=[customer_name, order_id, description]
    )


def send_template_message(cfg, phone, template_name, variables):
    """
    Send a WhatsApp approved template message.
    variables: list of strings in order [var1, var2, var3...]
    """
    token    = cfg["access_token"]
    pid      = cfg["phone_number_id"]
    version  = cfg.get("api_version", "v19.0")
    url      = f"https://graph.facebook.com/{version}/{pid}/messages"
    headers  = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    components = []
    if variables:
        components.append({
            "type": "body",
            "parameters": [
                {"type": "text", "text": str(v)} for v in variables
            ]
        })

    data = {
        "messaging_product": "whatsapp",
        "to":   phone,
        "type": "template",
        "template": {
            "name":     template_name,
            "language": {"code": "en"},
            "components": components
        }
    }

    try:
        resp = requests.post(url, headers=headers, json=data, timeout=10)
        if not resp.ok:
            print(f"[Template Error] {template_name} to {phone}: {resp.status_code} — {resp.text}")
        return resp
    except requests.exceptions.RequestException as e:
        print(f"[Template Failed] {template_name} to {phone}: {e}")
        return None


def send_plate_making_notification(cfg, phone, customer_name, order_id, description):
    """
    Send order_status_plate template notification to customer.
    Template variables: {{1}}=name, {{2}}=order_id, {{3}}=description
    """
    return send_template_message(
        cfg, phone,
        template_name="order_status_plate",
        variables=[customer_name, order_id, description]
    )


def send_template_message(cfg, phone, template_name, variables):
    """
    Send a WhatsApp approved template message.
    variables: list of strings in order e.g. ["Rahul", "5", "Visiting Cards"]
    """
    token   = cfg["access_token"]
    pid     = cfg["phone_number_id"]
    version = cfg.get("api_version", "v19.0")
    url     = f"https://graph.facebook.com/{version}/{pid}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    components = []
    if variables:
        components.append({
            "type": "body",
            "parameters": [
                {"type": "text", "text": str(v)} for v in variables
            ]
        })

    data = {
        "messaging_product": "whatsapp",
        "to":   phone,
        "type": "template",
        "template": {
            "name":     template_name,
            "language": {"code": "en"},
            "components": components
        }
    }

    try:
        resp = requests.post(url, headers=headers, json=data, timeout=10)
        if not resp.ok:
            print(f"[Template Error] {template_name} to {phone}: {resp.status_code} — {resp.text}")
        return resp
    except requests.exceptions.RequestException as e:
        print(f"[Template Failed] {template_name} to {phone}: {e}")
        return None


def send_plate_making_template(cfg, phone, customer_name, order_id, description):
    """
    Send order_status_plate template.
    Template: Hello {{1}}, order {{2}}, product {{3}}
    """
    send_template_message(
        cfg, phone,
        template_name="order_status_plate",
        variables=[customer_name, order_id, description]
    )

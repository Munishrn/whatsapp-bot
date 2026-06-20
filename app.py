import os
import traceback
import shelve
import threading
import time

from flask import Flask, request

from config_loader import (
    feature_enabled,
    get_client_config,
    reload_configs,
    get_status_map,
    is_final_status,
    is_cancelled_status,
    is_ready_status,
    skip_delivery_for_status,
)

from logic import (
    get_user_role,
    get_order_status,
    get_orders_by_date,
    get_orders_by_date_range,
    create_order,
    update_order,
    get_customer_phone,
    format_phone,
    get_today_str,
    parse_date,
    parse_delivery_datetime,
    format_delivery_str,
    get_unique_clients,
    get_stale_orders,
    get_late_orders,
    get_order_desc,
    get_customer_name,
    get_current_status,
)

from whatsapp import (
    send_text,
    send_back_button,
    send_staff_menu,
    send_customer_menu,
    send_status_list,
    send_create_order_type,
    send_existing_clients_list,
    send_update_options,
    send_view_options,
    send_date_options,
    send_delivery_date_picker,
    send_delivery_time_picker,
    send_plate_making_notification,
)

from logger import log_conversation, log_error, cleanup_old_logs
from sheets import archive_old_rows

app = Flask(__name__)

STATE_FILE = "user_state"
TEMP_FILE  = "temp_data"

# Track late delivery notifications per client
notified_late = {}


# ── State helpers ─────────────────────────────────────────────────────────────

def _key(cfg, phone):
    """Unique key combining client ID and phone."""
    return f"{cfg['phone_number_id']}:{phone}"


def get_state(cfg, phone):
    with shelve.open(STATE_FILE) as db:
        return db.get(_key(cfg, phone))


def set_state(cfg, phone, state):
    with shelve.open(STATE_FILE) as db:
        db[_key(cfg, phone)] = state


def clear_state(cfg, phone):
    with shelve.open(STATE_FILE) as db:
        db.pop(_key(cfg, phone), None)
    with shelve.open(TEMP_FILE) as db:
        db.pop(_key(cfg, phone), None)


def get_temp(cfg, phone):
    with shelve.open(TEMP_FILE) as db:
        return db.get(_key(cfg, phone), {})


def set_temp(cfg, phone, data):
    with shelve.open(TEMP_FILE) as db:
        db[_key(cfg, phone)] = data


def update_temp(cfg, phone, key, value):
    with shelve.open(TEMP_FILE) as db:
        k       = _key(cfg, phone)
        current = db.get(k, {})
        current[key] = value
        db[k] = current


# ── Notification helpers ──────────────────────────────────────────────────────

def notify_ready(cfg, phone, order_id, description=""):
    msg = f"_🚚 Your order is Ready to be picked!_\n_Order ID: {order_id}_"
    if description:
        msg += f"\n_Product: {description}_"
    send_text(cfg, phone, msg)
    log_conversation(cfg, phone, "customer", "outgoing", msg)


def notify_cancelled(cfg, phone, order_id, description=""):
    msg = f"_❌ We're sorry, your order has been cancelled._\n_Order ID: {order_id}_"
    if description:
        msg += f"\n_Product: {description}_"
    msg += "\n_Please contact us for more details._"
    send_text(cfg, phone, msg)
    log_conversation(cfg, phone, "customer", "outgoing", msg)


def send_order_created_notification(cfg, customer_phone, customer_name, order_id, description, status, delivery_str=""):
    """
    Send order created notification to customer.
    Uses WhatsApp template if status has one configured, else regular message.
    """
    template_map  = cfg.get("status_templates", {})
    template_name = template_map.get(status.strip().lower())

    def _regular_message():
        if delivery_str:
            msg = (
                f"_📦 Order Created!_\n_Order ID: {order_id}_\n"
                f"_Product: {description}_\n_Status: {status}_\n"
                f"_Expected Delivery: {delivery_str}_"
            )
        else:
            msg = (
                f"_📦 Order Created!_\n_Order ID: {order_id}_\n"
                f"_Product: {description}_\n_Status: {status}_"
            )
        send_text(cfg, customer_phone, msg)
        log_conversation(cfg, customer_phone, "customer", "outgoing", msg)

    if template_name:
        resp = send_plate_making_notification(cfg, customer_phone, customer_name, order_id, description)
        if resp is not None and resp.ok:
            log_conversation(cfg, customer_phone, "customer", "outgoing", f"[Template: {template_name}] Order {order_id} created - {status}")
        else:
            # ✅ Template failed (not approved yet, etc.) — fall back to regular message
            log_error(cfg, "send_order_created_notification", f"Template '{template_name}' failed, falling back to regular message")
            _regular_message()
    else:
        _regular_message()


def notify_status_update(cfg, phone, order_id, status, description="", delivery="", changed="status", customer_name=""):
    """Send status update — uses WhatsApp template if available, falls back to regular message."""

    # ✅ Use approved template for Plate Making
    template_map = cfg.get("status_templates", {})
    template_name = template_map.get(status.strip().lower())

    if template_name:
        resp = send_plate_making_notification(cfg, phone, customer_name or "Customer", order_id, description)
        if resp is not None and resp.ok:
            log_conversation(cfg, phone, "customer", "outgoing", f"[Template: {template_name}] Order {order_id} - {status}")
            return
        else:
            log_error(cfg, "notify_status_update", f"Template '{template_name}' failed, falling back to regular message")
            # Fall through to regular message below

    # Fallback — regular message for non-template statuses or failed template
    status_emojis = {
        "design making":      "🎨",
        "plate making":       "🖼️",
        "offset printing":    "🖨️",
        "ready to be picked": "✅",
        "out for delivery":   "🚚",
        "cancelled":          "❌",
    }
    emoji = status_emojis.get(status.strip().lower(), "📋")
    msg   = f"_{emoji} Order Update!_\n_Order ID: {order_id}_"
    if description:
        msg += f"\n_Product: {description}_"
    if changed == "status":
        msg += f"\n_✏️ Order status changed to: {status}_"
    elif changed == "delivery":
        msg += f"\n_Status: {status}_"
        if delivery:
            msg += f"\n_🕐 Expected delivery changed to: {delivery}_"
    elif changed == "both":
        msg += f"\n_✏️ Order status changed to: {status}_"
        if delivery:
            msg += f"\n_🕐 Expected delivery changed to: {delivery}_"
    send_text(cfg, phone, msg)
    log_conversation(cfg, phone, "customer", "outgoing", msg)


# ── Apply update helper ───────────────────────────────────────────────────────

def _apply_update(cfg, phone, order_id, update_type, new_status, delivery_str):
    if update_type == "both":
        success = update_order(order_id, new_status, cfg, delivery_str)
        if success:
            send_text(cfg, phone, f"✅ Order {order_id} updated\nStatus: {new_status}\nExpected Delivery: {delivery_str}")
            cp   = get_customer_phone(order_id, cfg)
            desc = get_order_desc(order_id, cfg)
            if cp:
                if is_ready_status(new_status, cfg):
                    notify_ready(cfg, cp, order_id, desc)
                elif is_cancelled_status(new_status, cfg):
                    notify_cancelled(cfg, cp, order_id, desc)
                else:
                    notify_status_update(cfg, cp, order_id, new_status, desc, delivery_str, changed="both")
        else:
            send_text(cfg, phone, f"❌ Order {order_id} not found.")
    else:
        current = get_current_status(order_id, cfg)
        success = update_order(order_id, current, cfg, delivery_str)
        if success:
            send_text(cfg, phone, f"✅ Delivery time updated for Order {order_id}\nNew Expected Delivery: {delivery_str}")
            cp   = get_customer_phone(order_id, cfg)
            desc = get_order_desc(order_id, cfg)
            if cp:
                notify_status_update(cfg, cp, order_id, current, desc, delivery_str, changed="delivery")
        else:
            send_text(cfg, phone, f"❌ Order {order_id} not found.")
    clear_state(cfg, phone)


# ── Late delivery checker ─────────────────────────────────────────────────────

def late_delivery_checker():
    while True:
        try:
            from config_loader import load_all_clients
            all_clients = load_all_clients()
            for pid, cfg in all_clients.items():
                client_key = cfg.get("business_name", pid)
                if client_key not in notified_late:
                    notified_late[client_key] = set()

                if not feature_enabled(cfg, "late_delivery_alert"):
                    continue
                late_orders = get_late_orders(cfg)
                for order in late_orders:
                    order_id = str(order["id"])
                    if order_id not in notified_late[client_key]:
                        msg = (
                            f"_⏰ We apologize for the delay on your order._\n"
                            f"_Order ID: {order_id}_\n"
                            f"_Product: {order['description']}_\n"
                            f"_Expected Delivery: {order['delivery']}_\n"
                            f"_Current Status: {order['status']}_\n\n"
                            f"_Our team is working on it. We will update you shortly. 🙏_"
                        )
                        send_text(cfg, order["phone"], msg)
                        log_conversation(cfg, order["phone"], "customer", "outgoing", msg)
                        notified_late[client_key].add(order_id)

                # Cleanup old logs daily (every 24hrs = 48 × 30min cycles)
                # We use a simple counter approach
        except Exception as e:
            print(f"[Late Checker Error] {e}")

        time.sleep(30 * 60)


checker_thread = threading.Thread(target=late_delivery_checker, daemon=True)
checker_thread.start()
print("[Late Delivery Checker] Started.")


def daily_cleanup():
    """
    Runs daily at midnight.
    Archives old orders and cleans up old logs for all clients.
    """
    import time as _time
    from datetime import datetime as _dt

    while True:
        now = _dt.now()
        # Calculate seconds until next midnight
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        from datetime import timedelta
        next_midnight = midnight + timedelta(days=1)
        seconds_until_midnight = (next_midnight - now).total_seconds()
        print(f"[Cleanup] Next cleanup at midnight ({int(seconds_until_midnight/3600)}hrs away)")
        _time.sleep(seconds_until_midnight)

        # Run cleanup for all clients
        try:
            from config_loader import load_all_clients
            all_clients = load_all_clients()
            for pid, cfg in all_clients.items():
                sheet_id      = cfg.get("google_sheet_id")
                retention     = cfg.get("order_retention_days", 30)
                business_name = cfg.get("business_name", pid)

                if not sheet_id:
                    continue

                try:
                    # Archive old orders
                    archived = archive_old_rows(
                        sheet_id,
                        source_tab="Orders",
                        archive_tab="Archived Orders",
                        date_col_index=5,  # COL_DATE
                        days=retention
                    )
                    if archived:
                        print(f"[Cleanup] {business_name}: Archived {archived} orders")

                    # Cleanup old conversation and error logs
                    cleanup_old_logs(cfg)

                except Exception as e:
                    print(f"[Cleanup Error] {business_name}: {e}")

        except Exception as e:
            print(f"[Cleanup Error] {e}")


cleanup_thread = threading.Thread(target=daily_cleanup, daemon=True)
cleanup_thread.start()
print("[Daily Cleanup] Started — runs at midnight.")


# ── Daily cleanup scheduler ───────────────────────────────────────────────────

def daily_cleanup():
    """
    Runs every night at midnight.
    Archives old orders and cleans old conversation/error logs.
    """
    from sheets import archive_old_rows
    from datetime import datetime, timedelta

    while True:
        now      = datetime.now()
        # Calculate seconds until next midnight
        midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        wait_sec = (midnight - now).total_seconds()
        print(f"[Cleanup] Next cleanup scheduled at midnight ({int(wait_sec/3600)}h {int((wait_sec%3600)/60)}m away)")
        time.sleep(wait_sec)

        # Run cleanup for all clients
        try:
            from config_loader import load_all_clients
            all_clients = load_all_clients()
            for pid, cfg in all_clients.items():
                sheet_id     = cfg.get("google_sheet_id")
                business     = cfg.get("business_name", pid)
                retain_days  = cfg.get("order_retention_days", 30)

                if not sheet_id:
                    continue

                try:
                    # Archive old orders
                    archived = archive_old_rows(
                        sheet_id,
                        source_tab="Orders",
                        archive_tab="Orders Archive",
                        date_col_index=5,  # COL_DATE
                        days=retain_days
                    )
                    if archived:
                        print(f"[Cleanup] {business}: Archived {archived} orders older than {retain_days} days")

                    # Clean old conversation and error logs
                    from logger import cleanup_old_logs
                    cleanup_old_logs(cfg)

                except Exception as e:
                    print(f"[Cleanup Error] {business}: {e}")

        except Exception as e:
            print(f"[Cleanup Error] {e}")


cleanup_thread = threading.Thread(target=daily_cleanup, daemon=True)
cleanup_thread.start()
print("[Daily Cleanup] Started — runs every midnight.")


# ── Webhook ───────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def health():
    from config_loader import load_all_clients
    clients = load_all_clients()
    return f"WhatsApp SaaS Bot — {len(clients)} client(s) active ✅", 200



@app.route("/webhook", methods=["GET"])
def verify():
    """Handle Meta webhook verification for all clients."""
    token     = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    # Check against all client verify tokens
    from config_loader import load_all_clients
    for pid, cfg in load_all_clients().items():
        if token == cfg.get("verify_token"):
            return challenge
    return "Verification failed", 403


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json

    try:
        entry = data.get("entry", [])
        if not entry:
            return "ok"
        changes = entry[0].get("changes", [])
        if not changes:
            return "ok"
        value = changes[0].get("value", {})

        # ✅ Identify client by phone_number_id from webhook payload
        phone_number_id = value.get("metadata", {}).get("phone_number_id")
        cfg = get_client_config(phone_number_id)

        if not cfg:
            print(f"[Webhook] Unknown phone_number_id: {phone_number_id}")
            return "ok"

        messages = value.get("messages", [])
        if not messages:
            return "ok"

        message    = messages[0]
        phone      = message["from"]
        role       = get_user_role(phone, cfg)
        state      = get_state(cfg, phone)
        status_map = get_status_map(cfg)

        # Log incoming message
        if "text" in message:
            log_conversation(cfg, phone, role, "incoming", message["text"]["body"])
        elif "interactive" in message:
            interactive = message["interactive"]
            btn = interactive.get("button_reply", {}).get("title") or \
                  interactive.get("list_reply", {}).get("title", "button")
            log_conversation(cfg, phone, role, "incoming", f"[Button: {btn}]")

        # ── INTERACTIVE ───────────────────────────────────────────────────
        if "interactive" in message:
            interactive = message["interactive"]
            if "button_reply" in interactive:
                button_id = interactive["button_reply"]["id"]
            elif "list_reply" in interactive:
                button_id = interactive["list_reply"]["id"]
            else:
                return "ok"

            if button_id == "back_to_menu":
                clear_state(cfg, phone)
                if role == "staff":
                    send_staff_menu(cfg, phone)
                else:
                    send_customer_menu(cfg, phone)

            elif button_id == "todays_orders":
                today = get_today_str()
                rows  = get_orders_by_date(today, phone, role, cfg)
                send_back_button(cfg, phone, rows)

            elif button_id == "broadcast_msg":
                customers = get_all_unique_customers(cfg)
                if not customers:
                    send_text(cfg, phone, "❌ No customers found.")
                    send_staff_menu(cfg, phone)
                else:
                    set_state(cfg, phone, "broadcast_select_customer")
                    send_broadcast_customer_list(cfg, phone, customers)

            elif button_id == "bc_all_customers" and state == "broadcast_select_customer":
                customers = get_all_unique_customers(cfg)
                update_temp(cfg, phone, "bc_recipients", [c["phone"] for c in customers])
                update_temp(cfg, phone, "bc_recipient_name", f"All Customers ({len(customers)})")
                set_state(cfg, phone, "broadcast_type_message")
                send_back_button(cfg, phone, f"📢 Broadcast to All {len(customers)} Customers\n\nType your message:")

            elif button_id.startswith("bc_customer_") and state == "broadcast_select_customer":
                cust_phone = button_id.replace("bc_customer_", "")
                cust_name  = interactive.get("list_reply", {}).get("title", cust_phone)
                update_temp(cfg, phone, "bc_recipients", [cust_phone])
                update_temp(cfg, phone, "bc_recipient_name", cust_name)
                set_state(cfg, phone, "broadcast_type_message")
                send_back_button(cfg, phone, f"📢 Broadcast to {cust_name}\n\nType your message:")

            elif button_id == "bc_confirm_send":
                d            = get_temp(cfg, phone)
                recipients   = d.get("bc_recipients", [])
                message      = d.get("bc_message", "")
                sent_count   = 0
                failed_count = 0
                for recipient in recipients:
                    try:
                        send_text(cfg, recipient, f"📢 Message from {cfg.get('business_name')}:\n\n{message}")
                        log_conversation(cfg, recipient, "customer", "outgoing", f"[Broadcast] {message}")
                        sent_count += 1
                    except Exception as e:
                        failed_count += 1
                        log_error(cfg, "broadcast_send", e)
                send_text(cfg, phone, f"✅ Broadcast sent!\n📤 Sent: {sent_count}\n❌ Failed: {failed_count}")
                clear_state(cfg, phone)
                send_staff_menu(cfg, phone)

            elif button_id == "bc_cancel":
                send_text(cfg, phone, "❌ Broadcast cancelled.")
                clear_state(cfg, phone)
                send_staff_menu(cfg, phone)

            elif button_id == "create_order":
                send_create_order_type(cfg, phone)

            elif button_id == "client_new":
                set_state(cfg, phone, "create_name")
                send_back_button(cfg, phone, "Enter Customer Name:")

            elif button_id == "client_existing":
                clients = get_unique_clients(cfg)
                if not clients:
                    send_text(cfg, phone, "❌ No existing clients found.")
                    send_create_order_type(cfg, phone)
                else:
                    set_state(cfg, phone, "select_existing_client")
                    send_existing_clients_list(cfg, phone, clients)

            elif button_id == "update_order":
                if not feature_enabled(cfg, "update_status"):
                    send_text(cfg, phone, "❌ Order updates are not enabled for your account.")
                    send_staff_menu(cfg, phone)
                else:
                    set_state(cfg, phone, "update_order_id")
                    send_back_button(cfg, phone, "Enter Order ID to update:")

            elif button_id == "update_status_only" and state == "update_what":
                update_temp(cfg, phone, "update_type", "status")
                set_state(cfg, phone, "update_status")
                send_status_list(cfg, phone, f"Select new status for Order {get_temp(cfg, phone).get('order_id')}:")

            elif button_id == "update_delivery_only" and state == "update_what":
                # ✅ Block if expected_delivery is disabled
                if not feature_enabled(cfg, "expected_delivery"):
                    send_text(cfg, phone, "❌ Expected delivery is not enabled for your account.")
                    send_staff_menu(cfg, phone)
                else:
                    update_temp(cfg, phone, "update_type", "delivery")
                    set_state(cfg, phone, "update_delivery_date")
                    send_delivery_date_picker(cfg, phone)

            elif button_id == "update_both" and state == "update_what":
                # ✅ If expected_delivery disabled, treat "both" as "status only"
                if not feature_enabled(cfg, "expected_delivery"):
                    update_temp(cfg, phone, "update_type", "status")
                else:
                    update_temp(cfg, phone, "update_type", "both")
                set_state(cfg, phone, "update_status")
                send_status_list(cfg, phone, f"Select new status for Order {get_temp(cfg, phone).get('order_id')}:")

            elif button_id == "view_orders":
                send_view_options(cfg, phone)

            elif button_id == "view_order":
                set_state(cfg, phone, "view_order")
                send_back_button(cfg, phone, "Enter Order ID to view:")

            elif button_id == "view_by_date":
                if not feature_enabled(cfg, "orders_by_date"):
                    send_text(cfg, phone, "❌ Orders by date is not enabled for your account.")
                    if role == "staff":
                        send_staff_menu(cfg, phone)
                    else:
                        send_customer_menu(cfg, phone)
                else:
                    set_state(cfg, phone, "view_by_date")
                    send_date_options(cfg, phone)

            elif button_id == "orders_last_30":
                if not feature_enabled(cfg, "orders_by_date"):
                    send_text(cfg, phone, "❌ This feature is not enabled for your account.")
                else:
                    result = get_orders_by_date_range(phone, role, cfg, days=30)
                    send_back_button(cfg, phone, result)
                clear_state(cfg, phone)

            elif button_id == "orders_last_60":
                if not feature_enabled(cfg, "orders_by_date"):
                    send_text(cfg, phone, "❌ This feature is not enabled for your account.")
                else:
                    result = get_orders_by_date_range(phone, role, cfg, days=60)
                    send_back_button(cfg, phone, result)
                clear_state(cfg, phone)

            elif button_id.startswith("filter_date_") and state == "view_by_date":
                date_val = button_id.replace("filter_date_", "")
                if date_val == "custom":
                    set_state(cfg, phone, "enter_specific_date")
                    send_back_button(cfg, phone, "Enter date as DD-MM-YYYY\nExample: 28-04-2026")
                else:
                    result = get_orders_by_date(date_val, phone, role, cfg)
                    send_back_button(cfg, phone, result)
                    clear_state(cfg, phone)

            elif button_id == "check_status":
                if not feature_enabled(cfg, "customer_tracking"):
                    send_text(cfg, phone, "❌ Order tracking is not enabled. Please contact us directly.")
                else:
                    set_state(cfg, phone, "check_status")
                    send_text(cfg, phone, "Enter your Order ID:")

            elif button_id.startswith("existing_client_") and state == "select_existing_client":
                parts        = button_id.split("_", 3)
                client_phone = parts[3] if len(parts) > 3 else ""
                client_name  = interactive.get("list_reply", {}).get("title", "")
                set_temp(cfg, phone, {"name": client_name, "phone": client_phone})
                set_state(cfg, phone, "create_description")
                send_back_button(cfg, phone, f"✅ Client: {client_name}\nEnter Description/Product:")

            elif button_id.startswith("del_date_"):
                date_val = button_id.replace("del_date_", "")
                if date_val == "custom":
                    if state and state.startswith("update"):
                        set_state(cfg, phone, "update_delivery_custom_date")
                    else:
                        set_state(cfg, phone, "create_delivery_custom_date")
                    send_back_button(cfg, phone, "Enter custom date as DD-MM-YYYY\nExample: 05-05-2026")
                else:
                    update_temp(cfg, phone, "delivery_date", date_val)
                    if state and state.startswith("update"):
                        set_state(cfg, phone, "update_delivery_time")
                    else:
                        set_state(cfg, phone, "create_delivery_time")
                    send_delivery_time_picker(cfg, phone, date_val)

            elif button_id.startswith("del_time_"):
                time_val = button_id.replace("del_time_", "")
                d        = get_temp(cfg, phone)

                if time_val == "custom":
                    delivery_date = d.get("delivery_date", "")
                    if state and state.startswith("update"):
                        set_state(cfg, phone, "update_delivery_custom_time")
                    else:
                        set_state(cfg, phone, "create_delivery_custom_time")
                    send_back_button(cfg, phone, f"Enter custom time for {delivery_date} as HH:MM\nExample: 14:30")
                else:
                    delivery_date = d.get("delivery_date", "")
                    dt_str  = f"{delivery_date} {time_val}"
                    dt      = parse_delivery_datetime(dt_str)
                    from datetime import datetime as dt_class
                    if dt and dt <= dt_class.now():
                        send_delivery_time_picker(cfg, phone, delivery_date)
                        send_text(cfg, phone, "⚠️ That time has already passed. Please select a future time slot.")
                        return "ok"
                    delivery_str = format_delivery_str(dt) if dt else dt_str

                    if state and state.startswith("update"):
                        order_id    = d.get("order_id")
                        update_type = d.get("update_type", "delivery")
                        new_status  = d.get("new_status")
                        _apply_update(cfg, phone, order_id, update_type, new_status, delivery_str)
                    else:
                        order_id = create_order(d["name"], d["description"], d["status"], d["phone"], delivery_str, cfg)
                        send_order_created_notification(cfg, d["phone"], d["name"], order_id, d["description"], d["status"], delivery_str)
                        send_text(cfg, phone, f"✅ Order Created\nOrder ID: {order_id}\nExpected Delivery: {delivery_str}")
                        clear_state(cfg, phone)

            elif button_id.startswith("status_") and state == "create_status":
                status = status_map.get(button_id)
                if not status:
                    send_text(cfg, phone, "❌ Invalid status selected.")
                    return "ok"
                update_temp(cfg, phone, "status", status)
                if skip_delivery_for_status(status, cfg) or not feature_enabled(cfg, "expected_delivery"):
                    d        = get_temp(cfg, phone)
                    order_id = create_order(d["name"], d["description"], status, d["phone"], "", cfg)
                    send_order_created_notification(cfg, d["phone"], d["name"], order_id, d["description"], status)
                    send_text(cfg, phone, f"✅ Order Created\nOrder ID: {order_id}\nStatus: {status}")
                    if is_cancelled_status(status, cfg):
                        notify_cancelled(cfg, d["phone"], order_id, d["description"])
                    clear_state(cfg, phone)
                else:
                    set_state(cfg, phone, "create_delivery_date")
                    send_delivery_date_picker(cfg, phone)

            elif button_id.startswith("status_") and state == "update_status":
                status      = status_map.get(button_id)
                if not status:
                    send_text(cfg, phone, "❌ Invalid status selected.")
                    return "ok"
                d           = get_temp(cfg, phone)
                order_id    = d.get("order_id")
                update_type = d.get("update_type", "status")

                if update_type == "both" and not skip_delivery_for_status(status, cfg):
                    update_temp(cfg, phone, "new_status", status)
                    set_state(cfg, phone, "update_delivery_date")
                    send_delivery_date_picker(cfg, phone)
                else:
                    # Status only OR final status (skip delivery)
                    success = update_order(order_id, status, cfg)
                    if success:
                        send_text(cfg, phone, f"✅ Order {order_id} updated to: {status}")
                        cp   = get_customer_phone(order_id, cfg)
                        desc = get_order_desc(order_id, cfg)
                        if cp:
                            if is_ready_status(status, cfg):
                                notify_ready(cfg, cp, order_id, desc)
                            elif is_cancelled_status(status, cfg):
                                notify_cancelled(cfg, cp, order_id, desc)
                            else:
                                delivery     = ""
                                cust_name    = get_customer_name(order_id, cfg)
                                notify_status_update(cfg, cp, order_id, status, desc, delivery, changed="status", customer_name=cust_name)
                    else:
                        send_text(cfg, phone, f"❌ Order {order_id} not found.")
                    clear_state(cfg, phone)

        # ── TEXT ──────────────────────────────────────────────────────────
        elif "text" in message:
            text = message["text"]["body"].strip()

            greetings = [
                "hi", "hello", "menu", "start", "hii", "hiii", "hey",
                "namaste", "namaskar", "sat sri akal", "sat shri akal", "ssa",
                "salaam", "adaab", "hy", "helo", "order", "help", "madad",
                "kya hai", "kya h", "bhai", "ji", "hello ji", "hi ji", "hey ji",
            ]

            if text.lower().strip() in greetings:
                clear_state(cfg, phone)
                if role == "staff":
                    if feature_enabled(cfg, "stale_orders_alert"):
                        stale = get_stale_orders(cfg, hours=cfg.get('stale_order_hours', 6))
                        if stale:
                            hours = cfg.get("stale_order_hours", 6)
                            mins  = int(hours * 60) if hours < 1 else int(hours)
                            unit  = "min(s)" if hours < 1 else "hour(s)"
                            lines = [f"⚠️ Stale Orders Alert — {len(stale)} order(s) not updated in {mins}+ {unit}:\n"]
                            for o in stale:
                                lines.append(
                                    f"🆔 Order {o['id']} | 👤 {o['customer']} | 📦 {o['description']}\n"
                                    f"   Status: {o['status']} | 🕐 Created: {o.get('created_at', 'N/A')}"
                                )
                            send_text(cfg, phone, "\n".join(lines))
                    send_staff_menu(cfg, phone)
                else:
                    send_customer_menu(cfg, phone)

            elif state == "enter_specific_date":
                parsed = parse_date(text)
                if not parsed:
                    send_text(cfg, phone, "❌ Invalid date format. Please enter as DD-MM-YYYY\nExample: 28-04-2026")
                    return "ok"
                result = get_orders_by_date(parsed, phone, role, cfg)
                send_back_button(cfg, phone, result)
                clear_state(cfg, phone)

            elif state == "create_name":
                set_temp(cfg, phone, {"name": text})
                set_state(cfg, phone, "create_description")
                send_back_button(cfg, phone, "Enter Description/Product:")

            elif state == "create_description":
                update_temp(cfg, phone, "description", text)
                d = get_temp(cfg, phone)
                if d.get("phone"):
                    set_state(cfg, phone, "create_status")
                    send_status_list(cfg, phone, "Select Order Status:")
                else:
                    set_state(cfg, phone, "create_phone")
                    send_back_button(cfg, phone, "Enter Customer Phone Number:")

            elif state == "create_phone":
                formatted = format_phone(text)
                if not formatted:
                    send_back_button(cfg, phone, "❌ Invalid number. Enter 10-digit or 12-digit with country code:")
                    return "ok"
                update_temp(cfg, phone, "phone", formatted)
                set_state(cfg, phone, "create_status")
                send_status_list(cfg, phone, "Select Order Status:")

            elif state == "create_delivery_custom_date":
                parsed = parse_date(text)
                if not parsed:
                    send_back_button(cfg, phone, "❌ Invalid date. Enter as DD-MM-YYYY\nExample: 14-05-2026")
                    return "ok"
                # ✅ Reject past dates
                from datetime import datetime as dt_class
                try:
                    sel_dt = dt_class.strptime(parsed, "%d-%m-%Y")
                    if sel_dt.date() < dt_class.now().date():
                        send_back_button(cfg, phone, f"❌ {parsed} is in the past.\nPlease enter today or a future date:")
                        return "ok"
                except Exception:
                    pass
                update_temp(cfg, phone, "delivery_date", parsed)
                set_state(cfg, phone, "create_delivery_time")
                send_delivery_time_picker(cfg, phone, parsed)

            elif state == "create_delivery_custom_time":
                from datetime import datetime as dt_class
                d      = get_temp(cfg, phone)
                dt_str = f"{d['delivery_date']} {text.strip()}"
                dt     = parse_delivery_datetime(dt_str)
                if not dt:
                    send_back_button(cfg, phone, "❌ Invalid time. Enter as HH:MM\nExample: 14:30")
                    return "ok"
                if dt <= dt_class.now():
                    send_back_button(cfg, phone, "⚠️ That time has already passed.\nEnter a future time as HH:MM")
                    return "ok"
                delivery_str = format_delivery_str(dt)
                order_id = create_order(d["name"], d["description"], d["status"], d["phone"], delivery_str, cfg)
                send_order_created_notification(cfg, d["phone"], d["name"], order_id, d["description"], d["status"], delivery_str)
                send_text(cfg, phone, f"✅ Order Created\nOrder ID: {order_id}\nExpected Delivery: {delivery_str}")
                clear_state(cfg, phone)

            elif state == "update_order_id":
                check   = get_order_status(text, phone, cfg)
                current = get_current_status(text, cfg)
                if "not found" in check.lower():
                    send_back_button(cfg, phone, f"❌ Order {text} not found.\n\nPlease enter a valid Order ID:")
                elif is_final_status(current, cfg):
                    send_back_button(cfg, phone, f"🔒 Order {text} is in '{current}' status and cannot be updated further.")
                else:
                    set_temp(cfg, phone, {"order_id": text})
                    set_state(cfg, phone, "update_what")
                    send_update_options(cfg, phone)

            elif state == "update_delivery_custom_date":
                parsed = parse_date(text)
                if not parsed:
                    send_back_button(cfg, phone, "❌ Invalid date. Enter as DD-MM-YYYY\nExample: 14-05-2026")
                    return "ok"
                # ✅ Reject past dates
                from datetime import datetime as dt_class
                try:
                    sel_dt = dt_class.strptime(parsed, "%d-%m-%Y")
                    if sel_dt.date() < dt_class.now().date():
                        send_back_button(cfg, phone, f"❌ {parsed} is in the past.\nPlease enter today or a future date:")
                        return "ok"
                except Exception:
                    pass
                update_temp(cfg, phone, "delivery_date", parsed)
                set_state(cfg, phone, "update_delivery_time")
                send_delivery_time_picker(cfg, phone, parsed)

            elif state == "update_delivery_time":
                pass  # Handled by del_time_ button

            elif state == "update_delivery_custom_time":
                from datetime import datetime as dt_class
                d      = get_temp(cfg, phone)
                dt_str = f"{d['delivery_date']} {text.strip()}"
                dt     = parse_delivery_datetime(dt_str)
                if not dt:
                    send_back_button(cfg, phone, "❌ Invalid time. Enter as HH:MM\nExample: 14:00")
                    return "ok"
                if dt <= dt_class.now():
                    send_back_button(cfg, phone, "⚠️ That time has already passed.\nEnter a future time as HH:MM")
                    return "ok"
                delivery_str = format_delivery_str(dt)
                _apply_update(cfg, phone, d.get("order_id"), d.get("update_type", "delivery"), d.get("new_status"), delivery_str)

            elif state == "view_order":
                result = get_order_status(text, phone, cfg)
                if "not found" in result.lower():
                    send_back_button(cfg, phone, result + "\n\nPlease enter a valid Order ID:")
                else:
                    send_back_button(cfg, phone, result)
                    clear_state(cfg, phone)

            elif state == "check_status":
                raw = get_order_status(text, phone, cfg)
                if "❌" not in raw and "not found" not in raw.lower():
                    send_text(cfg, phone, raw)
                    clear_state(cfg, phone)
                else:
                    send_back_button(cfg, phone, raw + "\n\nPlease enter a valid Order ID:")

            elif role == "customer" and text.strip().isdigit():
                raw = get_order_status(text.strip(), phone, cfg)
                if "❌" not in raw and "not found" not in raw.lower():
                    send_text(cfg, phone, raw)
                    clear_state(cfg, phone)
                else:
                    set_state(cfg, phone, "check_status")
                    send_back_button(cfg, phone, raw + "\n\nPlease enter a valid Order ID:")

            else:
                if role == "staff":
                    send_staff_menu(cfg, phone)
                else:
                    send_customer_menu(cfg, phone)

    except Exception:
        tb = traceback.format_exc()
        print(f"[Webhook Error]\n{tb}")
        try:
            log_error(cfg, "webhook", tb)
        except Exception:
            pass

    return "ok"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)

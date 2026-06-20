"""
logic.py — Order management using Google Sheets.
All functions accept `cfg` (client config dict) to support multiple clients.
"""

import threading
from datetime import datetime
from sheets import get_values, append_row, update_cell

sheets_lock = threading.Lock()

COL_ID       = 0
COL_NAME     = 1
COL_DESC     = 2
COL_STATUS   = 3
COL_PHONE    = 4
COL_DATE     = 5
COL_DELIVERY = 6
COL_CREATED  = 7

ORDERS_TAB = "Orders"
ORDERS_HEADERS = ["Order ID", "Customer", "Description", "Status", "Phone", "Date", "Delivery", "Created At"]

# ✅ Cache which sheet tabs have been verified — avoid duplicate header insertion
_verified_tabs = set()


def _get_row_value(row, col):
    return str(row[col]).strip() if len(row) > col and row[col] else ""


def _get_all_rows(cfg):
    """Get all order rows for a client."""
    from sheets import ensure_sheet_tab
    sheet_id = cfg["google_sheet_id"]
    # ✅ Only verify tab once per session — prevents duplicate headers on restart
    tab_key = f"{sheet_id}:{ORDERS_TAB}"
    if tab_key not in _verified_tabs:
        ensure_sheet_tab(sheet_id, ORDERS_TAB, ORDERS_HEADERS)
        _verified_tabs.add(tab_key)
    rows = get_values(sheet_id, ORDERS_TAB)
    return rows[1:] if len(rows) > 1 else []


def _find_row_num(cfg, order_id):
    """Find 1-based row number for an order (includes header)."""
    sheet_id = cfg["google_sheet_id"]
    rows     = get_values(sheet_id, ORDERS_TAB)
    for i, row in enumerate(rows[1:], start=2):
        if _get_row_value(row, COL_ID) == str(order_id):
            return i
    return None


def get_user_role(phone, cfg):
    return "staff" if phone in cfg.get("staff_numbers", []) else "customer"


def format_phone(number):
    number = str(number).strip()
    if not number.isdigit():
        return None
    if len(number) == 10:
        return "91" + number
    if len(number) == 12 and number.startswith("91"):
        return number
    return None


def get_today_str():
    return datetime.now().strftime("%d-%m-%Y")


def parse_date(text):
    text = text.strip()
    for fmt in ["%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d"]:
        try:
            return datetime.strptime(text, fmt).strftime("%d-%m-%Y")
        except ValueError:
            continue
    return None


def parse_delivery_datetime(text):
    text = text.strip()
    for fmt in ["%d-%m-%Y %H:%M", "%d/%m/%Y %H:%M", "%d-%m-%Y %I:%M %p"]:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def format_delivery_str(dt):
    return dt.strftime("%d-%m-%Y %I:%M %p")


def get_customer_phone(order_id, cfg):
    with sheets_lock:
        try:
            rows = _get_all_rows(cfg)
            for row in rows:
                if _get_row_value(row, COL_ID) == str(order_id):
                    return _get_row_value(row, COL_PHONE)
        except Exception as e:
            from logger import log_error
            log_error(cfg, "get_customer_phone", e)
    return None


def get_order_status(order_id, phone, cfg):
    with sheets_lock:
        try:
            rows = _get_all_rows(cfg)
            for row in rows:
                if _get_row_value(row, COL_ID) == str(order_id):
                    delivery   = _get_row_value(row, COL_DELIVERY) or "N/A"
                    date_val   = _get_row_value(row, COL_DATE) or "N/A"
                    status     = _get_row_value(row, COL_STATUS)
                    cust_phone = _get_row_value(row, COL_PHONE)

                    if phone in cfg.get("staff_numbers", []):
                        return (
                            f"Order ID: {_get_row_value(row, COL_ID)}\n"
                            f"Customer: {_get_row_value(row, COL_NAME)}\n"
                            f"Description: {_get_row_value(row, COL_DESC)}\n"
                            f"Status: {status}\n"
                            f"Phone: {cust_phone}\n"
                            f"Created Date: {date_val}\n"
                            f"Expected Delivery: {delivery}"
                        )

                    if cust_phone != str(phone):
                        return "❌ Not authorized to view this order. It belongs to some other customer."

                    # Hide delivery for final statuses
                    final = [s.lower() for s in cfg.get("final_statuses", [])]
                    msg = (
                        f"Order ID: {_get_row_value(row, COL_ID)}\n"
                        f"Customer: {_get_row_value(row, COL_NAME)}\n"
                        f"Description: {_get_row_value(row, COL_DESC)}\n"
                        f"Status: {status}\n"
                        f"Created Date: {date_val}"
                    )
                    if status.lower() not in final and delivery != "N/A":
                        msg += f"\nExpected Delivery: {delivery}"
                    return msg

        except Exception as e:
            from logger import log_error
            log_error(cfg, "get_order_status", e)
            return "❌ Order system not available. Please try again later."
    return "Order not found ❌"


def get_orders_by_date(date_str, phone, role, cfg):
    with sheets_lock:
        try:
            rows    = _get_all_rows(cfg)
            matched = []
            for row in rows:
                if not _get_row_value(row, COL_ID):
                    continue
                if _get_row_value(row, COL_DATE) != date_str:
                    continue
                delivery = _get_row_value(row, COL_DELIVERY) or "N/A"
                status   = _get_row_value(row, COL_STATUS)
                if role == "staff":
                    matched.append(
                        f"🆔 {_get_row_value(row, COL_ID)} | 👤 {_get_row_value(row, COL_NAME)} | 📦 {_get_row_value(row, COL_DESC)}\n"
                        f"   Status: {status} | 🕐 {delivery}"
                    )
                else:
                    if _get_row_value(row, COL_PHONE) == str(phone):
                        matched.append(
                            f"🆔 {_get_row_value(row, COL_ID)} | 📦 {_get_row_value(row, COL_DESC)}\n"
                            f"   Status: {status} | 🕐 {delivery}"
                        )
            if not matched:
                return f"No orders found for {date_str} 📭"
            header = f"📅 Orders for {date_str} ({len(matched)} found):\n"
            header += "─" * 30 + "\n"
            return header + "\n\n".join(matched)
        except Exception as e:
            from logger import log_error
            log_error(cfg, "get_orders_by_date", e)
            return "❌ Order system not available. Please try again later."


def get_orders_by_date_range(phone, role, cfg, days=30):
    """
    Returns all orders placed in the last `days` days.
    For customers, only their own orders are shown.
    """
    from datetime import timedelta
    cutoff = datetime.now() - timedelta(days=days)

    with sheets_lock:
        try:
            rows    = _get_all_rows(cfg)
            matched = []
            for row in rows:
                if not _get_row_value(row, COL_ID):
                    continue

                row_date_str = _get_row_value(row, COL_DATE)
                if not row_date_str:
                    continue
                try:
                    row_date = datetime.strptime(row_date_str, "%d-%m-%Y")
                except ValueError:
                    continue

                if row_date < cutoff:
                    continue

                delivery = _get_row_value(row, COL_DELIVERY) or "N/A"
                status   = _get_row_value(row, COL_STATUS)

                if role == "staff":
                    matched.append({
                        "date": row_date,
                        "text": (
                            f"🆔 {_get_row_value(row, COL_ID)} | 👤 {_get_row_value(row, COL_NAME)} | 📦 {_get_row_value(row, COL_DESC)}\n"
                            f"   Status: {status} | 📅 {row_date_str} | 🕐 {delivery}"
                        )
                    })
                else:
                    if _get_row_value(row, COL_PHONE) == str(phone):
                        matched.append({
                            "date": row_date,
                            "text": (
                                f"🆔 {_get_row_value(row, COL_ID)} | 📦 {_get_row_value(row, COL_DESC)}\n"
                                f"   Status: {status} | 📅 {row_date_str} | 🕐 {delivery}"
                            )
                        })

            if not matched:
                return f"No orders found in the last {days} days 📭"

            # Sort newest first
            matched.sort(key=lambda x: x["date"], reverse=True)

            header = f"📅 Orders in Last {days} Days ({len(matched)} found):\n"
            header += "─" * 30 + "\n"
            return header + "\n\n".join(m["text"] for m in matched)
        except Exception as e:
            from logger import log_error
            log_error(cfg, "get_orders_by_date_range", e)
            return "❌ Order system not available. Please try again later."


def generate_order_id(rows):
    max_id = 0
    for row in rows:
        val = _get_row_value(row, COL_ID)
        if val.isdigit():
            max_id = max(max_id, int(val))
    return str(max_id + 1)


def create_order(name, description, status, phone, delivery_str, cfg):
    with sheets_lock:
        try:
            rows       = _get_all_rows(cfg)
            order_id   = generate_order_id(rows)
            today      = get_today_str()
            created_at = datetime.now().strftime("%d-%m-%Y %H:%M")
            append_row(cfg["google_sheet_id"],
                      [order_id, name, description, status, phone, today, delivery_str, created_at],
                      sheet_name=ORDERS_TAB)
            return order_id
        except Exception as e:
            from logger import log_error
            log_error(cfg, "create_order", e)
            return None


def update_order(order_id, status, cfg, delivery_str=None):
    with sheets_lock:
        try:
            row_num = _find_row_num(cfg, order_id)
            if not row_num:
                return False
            update_cell(cfg["google_sheet_id"], row_num, COL_STATUS + 1, status, sheet_name=ORDERS_TAB)
            if delivery_str is not None:
                update_cell(cfg["google_sheet_id"], row_num, COL_DELIVERY + 1, delivery_str, sheet_name=ORDERS_TAB)
            return True
        except Exception as e:
            from logger import log_error
            log_error(cfg, "update_order", e)
    return False


def get_order_desc(order_id, cfg):
    with sheets_lock:
        try:
            rows = _get_all_rows(cfg)
            for row in rows:
                if _get_row_value(row, COL_ID) == str(order_id):
                    return _get_row_value(row, COL_DESC)
        except Exception:
            pass
    return ""


def get_customer_name(order_id, cfg):
    """Get customer name for an order."""
    with sheets_lock:
        try:
            rows = _get_all_rows(cfg)
            for row in rows:
                if _get_row_value(row, COL_ID) == str(order_id):
                    return _get_row_value(row, COL_NAME) or "Customer"
        except Exception:
            pass
    return "Customer"


def get_current_status(order_id, cfg):
    with sheets_lock:
        try:
            rows = _get_all_rows(cfg)
            for row in rows:
                if _get_row_value(row, COL_ID) == str(order_id):
                    return _get_row_value(row, COL_STATUS) or cfg.get("statuses", [""])[0]
        except Exception:
            pass
    return cfg.get("statuses", [""])[0]


def get_late_orders(cfg):
    now    = datetime.now()
    final  = [s.lower() for s in cfg.get("final_statuses", [])]
    with sheets_lock:
        try:
            rows = _get_all_rows(cfg)
            late = []
            for row in rows:
                if not _get_row_value(row, COL_ID):
                    continue
                status   = _get_row_value(row, COL_STATUS).lower()
                delivery = _get_row_value(row, COL_DELIVERY)
                if status in final or not delivery:
                    continue
                dt = parse_delivery_datetime(delivery)
                if dt and dt < now:
                    late.append({
                        "id":          _get_row_value(row, COL_ID),
                        "customer":    _get_row_value(row, COL_NAME),
                        "description": _get_row_value(row, COL_DESC),
                        "status":      _get_row_value(row, COL_STATUS),
                        "phone":       _get_row_value(row, COL_PHONE),
                        "delivery":    delivery,
                    })
            return late
        except Exception as e:
            from logger import log_error
            log_error(cfg, "get_late_orders", e)
            return []


def get_unique_clients(cfg):
    with sheets_lock:
        try:
            rows = _get_all_rows(cfg)
            seen = {}
            for row in rows:
                name  = _get_row_value(row, COL_NAME)
                phone = _get_row_value(row, COL_PHONE)
                if name and phone:
                    seen[name] = phone
            return [{"name": k, "phone": v} for k, v in seen.items()][:100]
        except Exception as e:
            from logger import log_error
            log_error(cfg, "get_unique_clients", e)
            return []


def get_stale_orders(cfg, hours=6):
    """
    Returns all non-final orders older than `hours`.
    Checks ALL orders regardless of date — including previous days.
    """
    from datetime import timedelta
    final     = [s.lower() for s in cfg.get("final_statuses", [])]
    threshold = datetime.now() - timedelta(hours=hours)
    with sheets_lock:
        try:
            rows  = _get_all_rows(cfg)
            stale = []
            for row in rows:
                if not _get_row_value(row, COL_ID):
                    continue
                status     = _get_row_value(row, COL_STATUS).lower()
                created_at = _get_row_value(row, COL_CREATED)

                # Skip final statuses
                if status in final:
                    continue

                # ✅ If no created_at — include anyway (old orders before feature)
                if not created_at:
                    stale.append({
                        "id":          _get_row_value(row, COL_ID),
                        "customer":    _get_row_value(row, COL_NAME),
                        "description": _get_row_value(row, COL_DESC),
                        "status":      _get_row_value(row, COL_STATUS),
                        "phone":       _get_row_value(row, COL_PHONE),
                        "created_at":  "N/A",
                    })
                    continue

                try:
                    created_dt = datetime.strptime(created_at, "%d-%m-%Y %H:%M")
                except ValueError:
                    continue

                # ✅ Include if older than threshold — no date restriction
                if created_dt <= threshold:
                    stale.append({
                        "id":          _get_row_value(row, COL_ID),
                        "customer":    _get_row_value(row, COL_NAME),
                        "description": _get_row_value(row, COL_DESC),
                        "status":      _get_row_value(row, COL_STATUS),
                        "phone":       _get_row_value(row, COL_PHONE),
                        "created_at":  created_at,
                    })
            return stale
        except Exception as e:
            from logger import log_error
            log_error(cfg, "get_stale_orders", e)
            return []

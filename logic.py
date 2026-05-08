import threading
import json
import os
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
from config import STAFF_NUMBERS

# ✅ Thread lock for concurrent request safety
sheets_lock = threading.Lock()

# Column indices (0-based)
COL_ID       = 0
COL_NAME     = 1
COL_DESC     = 2
COL_STATUS   = 3
COL_PHONE    = 4
COL_DATE     = 5
COL_DELIVERY = 6
COL_CREATED  = 7

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]


def get_sheet():
    """Connect to Google Sheet and return the active worksheet."""
    sheet_id = os.environ.get("GOOGLE_SHEET_ID")
    if not sheet_id:
        raise Exception("GOOGLE_SHEET_ID not set in environment.")

    # ✅ Try file first, then env variable
    creds_file = os.environ.get("GOOGLE_CREDENTIALS_FILE", "credentials.json")

    if os.path.exists(creds_file):
        # Load from file (local development)
        creds = Credentials.from_service_account_file(creds_file, scopes=SCOPES)
    else:
        # Load from environment variable (Render/production)
        creds_json = os.environ.get("GOOGLE_CREDENTIALS")
        if not creds_json:
            raise Exception("No Google credentials found.")
        # Fix common JSON formatting issues
        creds_json = creds_json.strip()
        if creds_json.startswith("'"):
            creds_json = creds_json[1:-1]
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)

    client = gspread.authorize(creds)
    sheet  = client.open_by_key(sheet_id)
    return sheet.sheet1


def get_all_rows():
    """Get all data rows from sheet (excluding header)."""
    sh   = get_sheet()
    rows = sh.get_all_values()
    return rows[1:] if len(rows) > 1 else []  # Skip header row


def get_user_role(phone):
    return "staff" if phone in STAFF_NUMBERS else "customer"


def format_phone(number):
    number = str(number).strip()
    if not number.isdigit():
        return None
    if len(number) == 10:
        return "91" + number
    if len(number) == 12 and number.startswith("91"):
        return number
    return None


def is_ready(status):
    return status.strip().lower() == "ready to be picked"


def is_out_for_delivery(status):
    return status.strip().lower() == "out for delivery"


def is_cancelled(status):
    return status.strip().lower() == "cancelled"


def get_today_str():
    return datetime.now().strftime("%d-%m-%Y")


def parse_date(text):
    text = text.strip()
    formats = ["%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d"]
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).strftime("%d-%m-%Y")
        except ValueError:
            continue
    return None


def parse_delivery_datetime(text):
    text = text.strip()
    formats = [
        "%d-%m-%Y %H:%M",
        "%d/%m/%Y %H:%M",
        "%d-%m-%Y %I:%M %p",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def format_delivery_str(dt):
    return dt.strftime("%d-%m-%Y %I:%M %p")


def _get_row_value(row, col):
    """Safely get value from row by column index."""
    return str(row[col]).strip() if len(row) > col and row[col] else ""


def get_customer_phone(order_id):
    with sheets_lock:
        try:
            rows = get_all_rows()
            for row in rows:
                if _get_row_value(row, COL_ID) == str(order_id):
                    return _get_row_value(row, COL_PHONE)
        except Exception as e:
            print(f"[Sheets Error] get_customer_phone: {e}")
    return None


def get_order_status(order_id, phone):
    with sheets_lock:
        try:
            rows = get_all_rows()
            for row in rows:
                if _get_row_value(row, COL_ID) == str(order_id):
                    delivery = _get_row_value(row, COL_DELIVERY) or "N/A"
                    date_val = _get_row_value(row, COL_DATE) or "N/A"
                    status   = _get_row_value(row, COL_STATUS)
                    cust_phone = _get_row_value(row, COL_PHONE)

                    if phone in STAFF_NUMBERS:
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

                    hide_delivery = {"ready to be picked", "out for delivery", "cancelled"}
                    msg = (
                        f"Order ID: {_get_row_value(row, COL_ID)}\n"
                        f"Customer: {_get_row_value(row, COL_NAME)}\n"
                        f"Description: {_get_row_value(row, COL_DESC)}\n"
                        f"Status: {status}\n"
                        f"Created Date: {date_val}"
                    )
                    if status.lower() not in hide_delivery and delivery != "N/A":
                        msg += f"\nExpected Delivery: {delivery}"
                    return msg

        except Exception as e:
            print(f"[Sheets Error] get_order_status: {e}")
            return "❌ Order system not available. Please try again later."

    return "Order not found ❌"


def get_orders_by_date(date_str, phone, role):
    with sheets_lock:
        try:
            rows    = get_all_rows()
            matched = []
            for row in rows:
                if not _get_row_value(row, COL_ID):
                    continue
                row_date = _get_row_value(row, COL_DATE)
                if row_date != date_str:
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
            print(f"[Sheets Error] get_orders_by_date: {e}")
            return "❌ Order system not available. Please try again later."


def generate_order_id(rows):
    """Generate next order ID from existing rows."""
    max_id = 0
    for row in rows:
        val = _get_row_value(row, COL_ID)
        if val.isdigit():
            max_id = max(max_id, int(val))
    return str(max_id + 1)


def create_order(name, description, status, phone, delivery_str=""):
    with sheets_lock:
        try:
            sh         = get_sheet()
            rows       = sh.get_all_values()
            data_rows  = rows[1:] if len(rows) > 1 else []
            order_id   = generate_order_id(data_rows)
            today      = get_today_str()
            created_at = datetime.now().strftime("%d-%m-%Y %H:%M")

            # Ensure header row exists
            if not rows:
                sh.append_row(["Order ID", "Customer", "Description", "Status", "Phone", "Date", "Delivery", "Created At"])

            sh.append_row([order_id, name, description, status, phone, today, delivery_str, created_at])
            return order_id
        except Exception as e:
            print(f"[Sheets Error] create_order: {e}")
            return None


def update_order(order_id, status, delivery_str=None):
    with sheets_lock:
        try:
            sh   = get_sheet()
            rows = sh.get_all_values()

            for i, row in enumerate(rows[1:], start=2):  # start=2 because row 1 is header
                if _get_row_value(row, COL_ID) == str(order_id):
                    # Update status (column D = col 4)
                    sh.update_cell(i, COL_STATUS + 1, status)
                    if delivery_str is not None:
                        sh.update_cell(i, COL_DELIVERY + 1, delivery_str)
                    return True
        except Exception as e:
            print(f"[Sheets Error] update_order: {e}")
    return False


def get_late_orders():
    """Returns orders past delivery time that are not in final status."""
    now = datetime.now()
    skip_statuses = {"ready to be picked", "out for delivery", "cancelled"}
    with sheets_lock:
        try:
            rows = get_all_rows()
            late = []
            for row in rows:
                if not _get_row_value(row, COL_ID):
                    continue
                status   = _get_row_value(row, COL_STATUS).lower()
                delivery = _get_row_value(row, COL_DELIVERY)
                if status in skip_statuses or not delivery:
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
            print(f"[Sheets Error] get_late_orders: {e}")
            return []


def get_unique_clients():
    with sheets_lock:
        try:
            rows = get_all_rows()
            seen = {}
            for row in rows:
                name  = _get_row_value(row, COL_NAME)
                phone = _get_row_value(row, COL_PHONE)
                if name and phone:
                    seen[name] = phone
            return [{"name": k, "phone": v} for k, v in seen.items()][:100]
        except Exception as e:
            print(f"[Sheets Error] get_unique_clients: {e}")
            return []


def get_stale_orders(hours=6):
    from datetime import timedelta
    skip_statuses = {"ready to be picked", "out for delivery", "cancelled"}
    threshold     = datetime.now() - timedelta(hours=hours)

    with sheets_lock:
        try:
            rows  = get_all_rows()
            stale = []
            for row in rows:
                if not _get_row_value(row, COL_ID):
                    continue
                status     = _get_row_value(row, COL_STATUS).lower()
                created_at = _get_row_value(row, COL_CREATED)

                if status in skip_statuses or not created_at:
                    continue

                try:
                    created_dt = datetime.strptime(created_at, "%d-%m-%Y %H:%M")
                except ValueError:
                    continue

                if created_dt > threshold:
                    continue

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
            print(f"[Sheets Error] get_stale_orders: {e}")
            return []

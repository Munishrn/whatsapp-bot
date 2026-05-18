"""
logger.py — Logs conversations and errors to Google Sheets.
Each client has two extra tabs: Conversations and Errors.
Auto-deletes entries older than 30 days.
"""

import threading
from datetime import datetime
from sheets import append_row, ensure_sheet_tab, delete_old_rows

log_lock = threading.Lock()

CONV_TAB    = "Conversations"
ERROR_TAB   = "Errors"
CONV_HEADERS  = ["Timestamp", "Business", "Phone", "Role", "Direction", "Message"]
ERROR_HEADERS = ["Timestamp", "Business", "Function", "Error Type", "Error Message"]

# ✅ Cache verified tabs to prevent duplicate headers
_verified_tabs = set()


def _ensure_tabs(sheet_id, business_name):
    """Make sure Conversations and Errors tabs exist — only once per session."""
    key = f"{sheet_id}"
    if key in _verified_tabs:
        return
    try:
        ensure_sheet_tab(sheet_id, CONV_TAB,  CONV_HEADERS)
        ensure_sheet_tab(sheet_id, ERROR_TAB, ERROR_HEADERS)
        _verified_tabs.add(key)
    except Exception as e:
        print(f"[Logger] Failed to ensure tabs: {e}")


def log_conversation(cfg, phone, role, direction, message):
    """
    Log a conversation message to the Conversations tab.
    direction: 'incoming' or 'outgoing'
    role: 'staff' or 'customer'
    """
    sheet_id      = cfg.get("google_sheet_id")
    business_name = cfg.get("business_name", "Unknown")

    if not sheet_id:
        return

    def _log():
        with log_lock:
            try:
                _ensure_tabs(sheet_id, business_name)
                timestamp = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
                # Truncate long messages
                msg = str(message)[:500] if message else ""
                append_row(sheet_id, [timestamp, business_name, phone, role, direction, msg],
                          sheet_name=CONV_TAB)
            except Exception as e:
                print(f"[Logger] log_conversation error: {e}")

    # Run in background thread to not slow down webhook response
    threading.Thread(target=_log, daemon=True).start()


def log_error(cfg, function_name, error):
    """Log an error to the Errors tab."""
    sheet_id      = cfg.get("google_sheet_id") if cfg else None
    business_name = cfg.get("business_name", "Unknown") if cfg else "Unknown"

    if not sheet_id:
        print(f"[Error] {function_name}: {error}")
        return

    def _log():
        with log_lock:
            try:
                _ensure_tabs(sheet_id, business_name)
                timestamp  = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
                error_type = type(error).__name__ if isinstance(error, Exception) else "Error"
                error_msg  = str(error)[:1000]
                append_row(sheet_id,
                          [timestamp, business_name, function_name, error_type, error_msg],
                          sheet_name=ERROR_TAB)
            except Exception as e:
                print(f"[Logger] log_error failed: {e}")

    threading.Thread(target=_log, daemon=True).start()


def cleanup_old_logs(cfg):
    """Delete logs older than 30 days. Called periodically."""
    sheet_id = cfg.get("google_sheet_id")
    if not sheet_id:
        return
    try:
        delete_old_rows(sheet_id, CONV_TAB,  date_col_index=0, days=30)
        delete_old_rows(sheet_id, ERROR_TAB, date_col_index=0, days=30)
        print(f"[Logger] Cleaned old logs for {cfg.get('business_name')}")
    except Exception as e:
        print(f"[Logger] cleanup_old_logs error: {e}")

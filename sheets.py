"""
sheets.py — Low-level Google Sheets API using requests only (no gspread).
Handles auth, reading, writing for any sheet ID.
"""

import os
import json
import time
import requests

TOKEN_CACHE = {"token": None, "expires_at": 0}


def _get_access_token():
    """Get OAuth2 access token using service account credentials."""
    now = time.time()
    if TOKEN_CACHE["token"] and TOKEN_CACHE["expires_at"] > now + 60:
        return TOKEN_CACHE["token"]

    creds_file = os.environ.get("GOOGLE_CREDENTIALS_FILE", "credentials.json")
    if os.path.exists(creds_file):
        with open(creds_file) as f:
            creds_dict = json.load(f)
    else:
        creds_json = os.environ.get("GOOGLE_CREDENTIALS", "").strip()
        if not creds_json:
            raise Exception("No Google credentials found.")
        creds_dict = json.loads(creds_json)

    import base64
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    now_int = int(time.time())
    header  = base64.urlsafe_b64encode(
        json.dumps({"alg": "RS256", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()

    payload = {
        "iss":   creds_dict["client_email"],
        "scope": "https://www.googleapis.com/auth/spreadsheets",
        "aud":   "https://oauth2.googleapis.com/token",
        "exp":   now_int + 3600,
        "iat":   now_int,
    }
    payload_b64   = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    signing_input = f"{header}.{payload_b64}".encode()

    private_key = serialization.load_pem_private_key(
        creds_dict["private_key"].encode(), password=None
    )
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    sig_b64   = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    jwt_token = f"{header}.{payload_b64}.{sig_b64}"

    resp = requests.post("https://oauth2.googleapis.com/token", data={
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion":  jwt_token,
    })
    data = resp.json()
    TOKEN_CACHE["token"]      = data["access_token"]
    TOKEN_CACHE["expires_at"] = now_int + data.get("expires_in", 3600)
    return TOKEN_CACHE["token"]


def _headers():
    return {
        "Authorization": f"Bearer {_get_access_token()}",
        "Content-Type":  "application/json"
    }


def _base(sheet_id):
    return f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}"


def get_values(sheet_id, sheet_name="Sheet1"):
    """Get all values from a sheet tab."""
    resp = requests.get(
        f"{_base(sheet_id)}/values/{sheet_name}",
        headers=_headers()
    )
    return resp.json().get("values", [])


def append_row(sheet_id, values, sheet_name="Sheet1"):
    """Append a row to a sheet tab."""
    requests.post(
        f"{_base(sheet_id)}/values/{sheet_name}:append",
        headers=_headers(),
        params={"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"},
        json={"values": [values]}
    )


def update_cell(sheet_id, row_num, col_num, value, sheet_name="Sheet1"):
    """Update a specific cell. row_num and col_num are 1-based."""
    col_letter = chr(64 + col_num)
    cell_range = f"{sheet_name}!{col_letter}{row_num}"
    requests.put(
        f"{_base(sheet_id)}/values/{cell_range}",
        headers=_headers(),
        params={"valueInputOption": "RAW"},
        json={"values": [[value]]}
    )


def ensure_sheet_tab(sheet_id, tab_name, headers):
    """Create a sheet tab with headers if it doesn't exist."""
    # Get existing sheets
    resp = requests.get(f"{_base(sheet_id)}", headers=_headers())
    existing = [s["properties"]["title"] for s in resp.json().get("sheets", [])]

    if tab_name not in existing:
        # Create the tab
        requests.post(
            f"{_base(sheet_id)}:batchUpdate",
            headers=_headers(),
            json={"requests": [{"addSheet": {"properties": {"title": tab_name}}}]}
        )
        # Add headers
        append_row(sheet_id, headers, sheet_name=tab_name)
        print(f"[Sheets] Created tab '{tab_name}' in sheet {sheet_id}")


def archive_old_rows(sheet_id, source_tab, archive_tab, date_col_index, days=30):
    """
    Move rows older than `days` from source_tab to archive_tab.
    date_col_index is 0-based column index containing the date.
    """
    from datetime import datetime, timedelta
    cutoff = datetime.now() - timedelta(days=days)

    rows = get_values(sheet_id, source_tab)
    if len(rows) <= 1:
        return 0  # Only header or empty

    header      = rows[0]
    data_rows   = rows[1:]
    to_archive  = []
    to_keep     = []

    for row in data_rows:
        if len(row) > date_col_index and row[date_col_index]:
            try:
                # Try parsing date from column
                date_str = str(row[date_col_index]).strip()[:10]  # DD-MM-YYYY
                row_date = datetime.strptime(date_str, "%d-%m-%Y")
                if row_date < cutoff:
                    to_archive.append(row)
                else:
                    to_keep.append(row)
            except Exception:
                to_keep.append(row)  # Keep if can't parse date
        else:
            to_keep.append(row)

    if not to_archive:
        return 0

    # Ensure archive tab exists with same headers
    ensure_sheet_tab(sheet_id, archive_tab, header)

    # Append old rows to archive tab
    for row in to_archive:
        append_row(sheet_id, row, sheet_name=archive_tab)

    # Rewrite source tab with only kept rows
    token    = _get_access_token()
    sheet_id_url = _base(sheet_id)

    # Clear source tab
    requests.post(
        f"{sheet_id_url}/values/{source_tab}:clear",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    )

    # Rewrite header + kept rows
    all_rows = [header] + to_keep
    requests.put(
        f"{sheet_id_url}/values/{source_tab}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        params={"valueInputOption": "RAW"},
        json={"values": all_rows}
    )

    print(f"[Sheets] Archived {len(to_archive)} rows from {source_tab} to {archive_tab}")
    return len(to_archive)


def delete_old_rows(sheet_id, tab_name, date_col_index, days=30):
    """
    Delete rows older than `days` days from a sheet tab.
    date_col_index is 0-based column index containing the timestamp.
    """
    from datetime import datetime, timedelta
    cutoff = datetime.now() - timedelta(days=days)

    rows = get_values(sheet_id, tab_name)
    if len(rows) <= 1:
        return  # Only header or empty

    rows_to_delete = []
    for i, row in enumerate(rows[1:], start=1):  # skip header
        if len(row) > date_col_index:
            try:
                row_date = datetime.strptime(row[date_col_index][:16], "%d-%m-%Y %H:%M")
                if row_date < cutoff:
                    rows_to_delete.append(i + 1)  # 1-based, +1 for header
            except Exception:
                pass

    if not rows_to_delete:
        return

    # Delete in reverse order to preserve indices
    sheet_meta = requests.get(f"{_base(sheet_id)}", headers=_headers()).json()
    sheet_tab_id = None
    for s in sheet_meta.get("sheets", []):
        if s["properties"]["title"] == tab_name:
            sheet_tab_id = s["properties"]["sheetId"]
            break

    if sheet_tab_id is None:
        return

    delete_requests = []
    for row_num in sorted(rows_to_delete, reverse=True):
        delete_requests.append({
            "deleteDimension": {
                "range": {
                    "sheetId":    sheet_tab_id,
                    "dimension":  "ROWS",
                    "startIndex": row_num - 1,
                    "endIndex":   row_num
                }
            }
        })

    if delete_requests:
        requests.post(
            f"{_base(sheet_id)}:batchUpdate",
            headers=_headers(),
            json={"requests": delete_requests}
        )
        print(f"[Sheets] Deleted {len(delete_requests)} old rows from {tab_name}")


def archive_old_rows(sheet_id, source_tab, archive_tab, date_col_index, days=30):
    """
    Move rows older than `days` from source_tab to archive_tab.
    date_col_index is 0-based column index containing the date.
    """
    from datetime import datetime, timedelta
    cutoff = datetime.now() - timedelta(days=days)

    # Ensure archive tab exists with same headers
    source_rows = get_values(sheet_id, source_tab)
    if not source_rows:
        return 0

    headers = source_rows[0]
    ensure_sheet_tab(sheet_id, archive_tab, headers)

    # Find rows to archive
    rows_to_archive = []
    row_indices_to_delete = []

    for i, row in enumerate(source_rows[1:], start=1):
        if len(row) > date_col_index:
            try:
                date_str = str(row[date_col_index])[:10]
                # Try multiple formats
                for fmt in ["%d-%m-%Y", "%Y-%m-%d"]:
                    try:
                        row_date = datetime.strptime(date_str, fmt)
                        if row_date < cutoff:
                            rows_to_archive.append(row)
                            row_indices_to_delete.append(i + 1)  # 1-based with header
                        break
                    except ValueError:
                        continue
            except Exception:
                pass

    if not rows_to_archive:
        return 0

    # Append to archive tab
    for row in rows_to_archive:
        append_row(sheet_id, row, sheet_name=archive_tab)

    # Delete from source tab in reverse order
    sheet_meta = requests.get(f"{_base(sheet_id)}", headers=_headers()).json()
    source_sheet_id = None
    for s in sheet_meta.get("sheets", []):
        if s["properties"]["title"] == source_tab:
            source_sheet_id = s["properties"]["sheetId"]
            break

    if source_sheet_id is None:
        return 0

    delete_requests = []
    for row_num in sorted(row_indices_to_delete, reverse=True):
        delete_requests.append({
            "deleteDimension": {
                "range": {
                    "sheetId":    source_sheet_id,
                    "dimension":  "ROWS",
                    "startIndex": row_num - 1,
                    "endIndex":   row_num
                }
            }
        })

    if delete_requests:
        requests.post(
            f"{_base(sheet_id)}:batchUpdate",
            headers=_headers(),
            json={"requests": delete_requests}
        )

    print(f"[Sheets] Archived {len(rows_to_archive)} rows from {source_tab} to {archive_tab}")
    return len(rows_to_archive)

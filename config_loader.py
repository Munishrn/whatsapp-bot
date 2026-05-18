import os
import json
import glob

# Cache loaded configs in memory
_config_cache = {}


def load_all_clients():
    """
    Load client configs from two sources:
    1. Local files in clients/ folder (for local development)
    2. Environment variables prefixed with CLIENT_ (for Render/production)
    """
    configs = {}

    # ✅ Source 1 — Local JSON files (development)
    pattern = os.path.join(os.path.dirname(__file__), "clients", "*.json")
    for filepath in glob.glob(pattern):
        if filepath.endswith(".example"):
            continue
        try:
            with open(filepath, encoding="utf-8-sig") as f:
                cfg = json.load(f)
            phone_number_id = cfg.get("phone_number_id")
            if phone_number_id:
                configs[phone_number_id] = cfg
                print(f"[Config] Loaded client from file: {cfg.get('business_name')} ({phone_number_id})")
        except Exception as e:
            print(f"[Config Error] Failed to load {filepath}: {e}")

    # ✅ Source 2 — Environment variables (Render production)
    # Any env var starting with CLIENT_ is treated as a client config
    # Example: CLIENT_SAHIL_PROCESSORS = { entire JSON }
    for key, value in os.environ.items():
        if key.startswith("CLIENT_"):
            try:
                cfg = json.loads(value)
                phone_number_id = cfg.get("phone_number_id")
                if phone_number_id and phone_number_id not in configs:
                    configs[phone_number_id] = cfg
                    print(f"[Config] Loaded client from env: {cfg.get('business_name')} ({phone_number_id})")
            except Exception as e:
                print(f"[Config Error] Failed to parse env {key}: {e}")

    if not configs:
        print("[Config] ⚠️ No clients loaded! Check clients/ folder or CLIENT_* environment variables.")

    return configs


def get_client_config(phone_number_id):
    """
    Get client config by phone_number_id.
    Reloads from disk if not cached.
    """
    global _config_cache
    if not _config_cache:
        _config_cache = load_all_clients()
    return _config_cache.get(phone_number_id)


def reload_configs():
    """Force reload all client configs."""
    global _config_cache
    _config_cache = load_all_clients()
    return _config_cache


def get_status_map(cfg):
    """
    Build STATUS_MAP from client config statuses list.
    Returns dict like {"status_0": "Design Making", ...}
    """
    status_map = {}
    for i, status in enumerate(cfg.get("statuses", [])):
        key = f"status_{i}"
        status_map[key] = status
    return status_map


def is_final_status(status, cfg):
    """Check if status is a final/locked status for this client."""
    final = [s.lower() for s in cfg.get("final_statuses", [])]
    return status.strip().lower() in final


def is_cancelled_status(status, cfg):
    """Check if status means cancelled for this client."""
    cancelled = cfg.get("cancelled_status", "Cancelled")
    return status.strip().lower() == cancelled.lower()


def is_ready_status(status, cfg):
    """Check if status means ready to pick for this client."""
    ready = cfg.get("ready_status", "Ready to be picked")
    return status.strip().lower() == ready.lower()


def skip_delivery_for_status(status, cfg):
    """Check if delivery date should be skipped for this status."""
    skip = [s.lower() for s in cfg.get("delivery_statuses", [])]
    return status.strip().lower() in skip


# ── Feature flags ─────────────────────────────────────────────────────────────

def feature_enabled(cfg, feature):
    """
    Check if a feature is enabled for this client.
    Features are defined in client config under "features" key.
    All features enabled by default if not specified.

    Available features:
    - expected_delivery   : staff can set/update delivery date+time
    - update_status       : staff can update order status
    - orders_by_date      : staff/customer can filter orders by date
    - existing_client     : staff can select existing client when creating order
    - stale_orders_alert  : staff gets alert for stale orders on login
    - late_delivery_alert : customer gets notified when delivery time passed
    - customer_tracking   : customer can track their own orders
    """
    features = cfg.get("features", {})
    return features.get(feature, True)  # Default: all features enabled

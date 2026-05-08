from dotenv import load_dotenv
import os

load_dotenv()

ACCESS_TOKEN    = os.environ.get("ACCESS_TOKEN", "")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "")
VERIFY_TOKEN    = os.environ.get("VERIFY_TOKEN", "my_verify_token")

API_VERSION = "v19.0"

STAFF_NUMBERS = [
    "919779986649"
]

STATUS_MAP = {
    "status_design":    "Design Making",
    "status_plate":     "Plate Making",
    "status_printing":  "Offset Printing",
    "status_ready":     "Ready to be picked",
    "status_delivery":  "Out for delivery",
    "status_cancelled": "Cancelled",
}

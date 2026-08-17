import os
import json
import hmac
import hashlib
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("PSEUDOGRAM_API_KEY") or os.getenv("API_KEY")

if not API_KEY:
    raise RuntimeError("PSEUDOGRAM_API_KEY is not loaded from .env")

payload = {
    "event_id": "test_event_001",
    "event_type": "comment.created",
    "sent_at": "2026-08-17T10:00:00.000Z",
    "data": {
        "comment_id": "test_comment_001",
        "post_id": "test_post_001",
        "text": "PRICE please",
        "created_at": "2026-08-17T09:59:59.000Z",
        "from": {
            "user_id": "test_user_001",
            "username": "testuser"
        }
    }
}

# IMPORTANT:
# Sign the exact bytes that will be sent.
body = json.dumps(
    payload,
    separators=(",", ":")
).encode("utf-8")

signature = hmac.new(
    API_KEY.encode("utf-8"),
    body,
    hashlib.sha256
).hexdigest()

headers = {
    "Content-Type": "application/json",
    "X-PseudoGram-Signature": f"sha256={signature}"
}

url = "https://linkplease-assignment-b5b0.onrender.com/webhook"

response = requests.post(
    url,
    data=body,
    headers=headers,
    timeout=10
)

print("STATUS:", response.status_code)
print("BODY:", response.text)
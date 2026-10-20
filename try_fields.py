import json
import re
import sys

import requests

url = sys.argv[1]
phone = sys.argv[2] if len(sys.argv) > 2 else "972501234567"
base = re.match(r"https?://[^/]+", url).group(0)

HEAD = {
    "User-Agent": ("Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": base,
    "Referer": base + "/",
}

bodies = [
    {"phone": phone},
    {"phoneNumber": phone},
    {"mobile": phone},
    {"msisdn": phone},
    {"phone_number": phone},
    {"email": phone},
    {"username": phone},
]

for b in bodies:
    try:
        r = requests.post(url, data=json.dumps(b).encode(),
                          headers=HEAD, timeout=15)
        print(json.dumps(b), "->", r.status_code,
              r.headers.get("content-type"), "|",
              (r.text or "")[:250].replace("\n", " "))
    except Exception as e:
        print(json.dumps(b), "-> ERROR", e)

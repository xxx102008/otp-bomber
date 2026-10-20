import sys
import requests

url = sys.argv[1]
phone = sys.argv[2]

for field in ("phone", "phoneNumber", "mobile"):
    try:
        r = requests.post(url, json={field: phone}, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
            "Content-Type": "application/json",
        })
        print(field, "->", r.status_code, (r.text or "")[:200].replace("\n", " "))
    except Exception as e:
        print(field, "-> ERROR", e)

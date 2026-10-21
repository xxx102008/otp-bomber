#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""שולח בקשה אחת ומדפיס מה חזר. שימוש: python test_one.py URL [מספר]"""

import re
import sys

import requests

url = sys.argv[1]
phone = sys.argv[2] if len(sys.argv) > 2 else "972501234567"
base = re.match(r"https?://[^/]+", url).group(0)

r = requests.post(url, data='{"phone":"%s"}' % phone, timeout=15, headers={
    "User-Agent": ("Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"),
    "Content-Type": "application/json",
    "Origin": base,
    "Referer": base + "/",
})
print("STATUS:", r.status_code)
print("CT:", r.headers.get("content-type"))
print("LEN:", len(r.text))
print("FINAL URL:", r.url)
print("---- body ----")
print(r.text[:1500])

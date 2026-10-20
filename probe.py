#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probe.py v2 - מאתר כתובות OTP אמיתיות.
מסנן אתרי catch-all על ידי השוואה לכתובת דמה.

שימוש:
    python probe.py shufersal.co.il
    python probe.py shufersal.co.il 972501234567
"""

import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests

TARGET = sys.argv[1]
NUMBER = sys.argv[2] if len(sys.argv) > 2 else "972501234567"

TIMEOUT = 12
THREADS = 10

UA = ("Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36")

PATHS = [
    "/api/auth/send-otp", "/api/auth/otp", "/api/send-otp", "/api/otp/send",
    "/api/v1/auth/otp", "/api/v1/send-otp", "/api/v1/auth/send-otp",
    "/api/v2/auth/otp", "/auth/send-otp", "/auth/otp", "/send-otp",
    "/otp/send", "/api/send-code", "/api/user/send-otp",
    "/api/v1/otp/send", "/api/v1/sms/send", "/api/v1/user/send-otp",
    "/api/v1/phone/send-code", "/api/v1/auth/sms", "/api/v1/auth/send-code",
    "/api/v1/user/otp", "/api/v1/verify/send",
    "/api/v2/otp/send", "/api/v2/auth/sms", "/api/v2/sms/send",
    "/api/v2/send-otp", "/api/v2/user/send-otp",
    "/user/send-otp", "/auth/phone/send", "/auth/sms", "/sms/send",
    "/api/sms/send", "/api/auth/sms", "/api/auth/send-code",
    "/api/user/send-code", "/api/phone/send-code", "/api/verify/send",
]

BAD = ('"error"', '"success":false', '"status":false', '"ok":false',
       '"valid":false', '"result":false', "invalid", "required",
       "not found", "expired", "too many", "not exist", "missing",
       "unknown", "unrecognized")
OTP_WORDS = ("otp", "verification code", "one time", "one-time",
             "send sms", "sent", "verification")


def hdr(url):
    base = re.match(r"https?://[^/]+", url).group(0)
    return {
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
        "Content-Type": "application/json",
        "Origin": base,
        "Referer": base + "/",
        "sec-ch-ua-mobile": "?1",
        "sec-ch-ua-platform": '"Android"',
        "sec-fetch-site": "same-origin",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
    }


def fetch(url):
    try:
        return requests.post(url, data='{"phone":"%s"}' % NUMBER,
                             headers=hdr(url), timeout=TIMEOUT)
    except Exception:
        return None


def classify(r, base):
    if r is None:
        return ("DEAD", "לא מגיב")
    c = r.status_code
    ct = (r.headers.get("content-type") or "").lower()
    body = r.text or ""
    low = body.lower()

    if c in (404, 405, 410):
        return ("DEAD", "HTTP %d" % c)
    if c == 429:
        return ("THROTTLED", "429 - אנטי-בוט")

    # ---- ההשוואה החשובה: זהה לדף הדמה? ----
    if base is not None and base.status_code == c:
        b = base.text or ""
        if abs(len(body) - len(b)) < 40 and body[:150] == b[:150]:
            return ("SAME", "זהה לדף דמה: " + body[:45].replace("\n", " "))

    if "captcha" in low or "recaptcha" in low:
        return ("CAPTCHA", "דורש קפצ'ה")
    if c in (400, 401, 403, 422):
        return ("EXISTS", "HTTP %d - הנתיב קיים" % c)
    if c != 200:
        return ("DEAD", "HTTP %d" % c)

    if "json" in ct:
        if any(x in low for x in BAD):
            return ("EXISTS", "JSON שגיאה: " + body[:60].replace("\n", " "))
        return ("REAL", "JSON חיובי: " + body[:60].replace("\n", " "))

    if "html" in ct and len(body) > 1500:
        return ("HTML", "דף HTML גדול: " + body[:45].replace("\n", " "))

    if any(w in low for w in OTP_WORDS):
        return ("REAL", "טקסט עם מילות קוד: " + body[:60].replace("\n", " "))

    return ("EXISTS", "200 לא ברור: " + body[:60].replace("\n", " "))


def hit(url, base):
    for attempt in range(3):
        r = fetch(url)
        tag, why = classify(r, base)
        if tag == "THROTTLED" and attempt < 2:
            time.sleep(3)
            continue
        return (url, tag, why)
    return (url, tag, why)


def main():
    if TARGET.startswith("http"):
        hosts = [re.match(r"https?://[^/]+", TARGET).group(0)]
        pairs = [(TARGET, hosts[0])]
    else:
        d = TARGET.strip().rstrip("/").replace("https://", "").replace("http://", "")
        hosts = [d] if d.startswith(("www.", "api.")) else [d, "www." + d, "api." + d]
        pairs = [("https://" + h + p, h) for h in hosts for p in PATHS]

    print("בודק %d כתובות עם %s ...\n" % (len(pairs), NUMBER))

    bases = {}
    for h in hosts:
        bases[h] = fetch("https://" + h + "/api/__nope__xyz")

    with ThreadPoolExecutor(max_workers=THREADS) as ex:
        out = list(ex.map(lambda pu: hit(pu[0], bases.get(pu[1])), pairs))

    order = {"REAL": 0, "CAPTCHA": 1, "EXISTS": 2, "THROTTLED": 3,
             "HTML": 4, "SAME": 5, "DEAD": 6}
    out.sort(key=lambda x: (order.get(x[1], 9), x[0]))

    printed = {}
    for url, tag, why in out:
        if tag == "DEAD":
            continue
        printed[tag] = printed.get(tag, 0) + 1
        if tag in ("SAME", "HTML") and printed[tag] > 4:
            continue
        print("  %-9s %-56s %s" % ("[" + tag + "]", url, why))

    print("\n" + "-" * 58)
    for tag in ("REAL", "EXISTS", "CAPTCHA", "THROTTLED", "HTML", "SAME"):
        if printed.get(tag):
            print("  %-10s %d" % (tag, printed[tag]))

    reals = [u for u, t, w in out if t == "REAL"]
    print("\n" + "=" * 58)
    if reals:
        print("  %d כתובות REAL:" % len(reals))
        for u in reals:
            print("  " + u + '|POST|{"phone":"{phone}"}')
    else:
        print("  אין REAL.")
        if printed.get("SAME"):
            print("  רוב התשובות זהות לדף הדמה -> האתר מגיש דף אחד לכל נתיב.")
            print("  במקרה כזה צריך F12.")


if __name__ == "__main__":
    main()

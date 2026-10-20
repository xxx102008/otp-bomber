#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sync_sites.py  -  finds SMS/OTP bomber projects on GitHub, digs out their
endpoint lists, and rebuilds sites.txt. Run once, then run bomber.py.
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "sites.txt")
BACKUP = os.path.join(HERE, "sites_backup.txt")

# ---- where to look ----
QUERIES = [
    "sms+bomber",
    "otp+bomber",
    "smsbomber",
    "sms+bomber+api",
    "otp+sender+api",
]
MAX_REPOS = 15
MAX_FILES_PER_REPO = 4

# ---- extra direct sources (used as backup) ----
DIRECT = [
    "https://raw.githubusercontent.com/Hamed-Fakoori/sms-bomber/main/providers.json",
    "https://raw.githubusercontent.com/Hamed-Fakoori/sms-bomber/master/providers.json",
    "https://raw.githubusercontent.com/AvinashReddy3108/YetAnotherSMSBomber/master/services.yaml",
    "https://raw.githubusercontent.com/AvinashReddy3108/YetAnotherSMSBomber/master/api_config.json",
    "https://raw.githubusercontent.com/WeAreTeamX/xbomber-node-community-edition/main/api.json",
]

FILE_HINT = re.compile(
    r"(api|provider|endpoint|site|service|url|config|bomber|list)", re.I)
GOOD_EXT = (".json", ".txt", ".yaml", ".yml", ".js", ".ts", ".py", ".csv")

URL_RE = re.compile(r"https?://[^\s\"'<>\)\]\},;]+")
DOM_RE = re.compile(
    r"\b((?:[a-z0-9][a-z0-9\-]{0,62}\.)+"
    r"(?:com|net|org|io|co|app|dev|in|de|fr|es|it|pl|cz|ro|nl|be|se|no|dk|"
    r"fi|tr|ae|sa|pk|bd|id|my|sg|ph|th|vn|jp|kr|br|mx|ar|cl|za|ng|ke|eg|ru|"
    r"ua|gr|pt|ch|at|hu|bg|sk|lt|lv|ee|il|us|ca|au|nz|ie|uk|me|tv|xyz|shop|"
    r"store|online))"
    r"(?:/[^\s\"'<>\)\]\},;]*)?", re.I)

PLACEHOLDERS = ("{mobile}", "{number}", "{phone_number}", "{phoneNumber}",
                "{tel}", "{msisdn}", "{mobileNumber}", "{phone}",
                "<phone>", "<mobile>", "<number>", "%s")

KEEP = ("otp", "sms", "code", "verify", "verif", "auth", "login", "send",
        "mobile", "phone", "signup", "register", "token", "user")

SKIP_HOST = ("github", "githubusercontent", "npmjs", "w3.org", "schema.org",
             "googleapis", "gstatic", "jquery", "cloudflare", "fontawesome",
             "unpkg", "jsdelivr", "shields.io", "badge", "localhost",
             "example.com", "yoursite", "mysite", "test.com")


def get(url, as_json=False):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/vnd.github+json" if as_json else "*/*",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        txt = r.read().decode("utf-8", "ignore")
    return json.loads(txt) if as_json else txt


def add(raw, sink, bare_ok=False):
    u = raw.strip().rstrip(",;.'\"\\")
    u = u.replace("&amp;", "&").replace("\\/", "/")
    for ph in PLACEHOLDERS:
        u = u.replace(ph, "{phone}")
    if not u.startswith("http"):
        u = "https://" + u
    if len(u) < 12 or len(u) > 220:
        return
    m = re.match(r"https?://([^/]+)(.*)", u)
    if not m:
        return
    host, path = m.group(1).lower(), m.group(2)
    if "." not in host or any(s in host for s in SKIP_HOST):
        return
    if host.endswith("."):
        return
    path = path.rstrip("/")

    if not path:
        if bare_ok:
            sink.setdefault(host, "https://" + host)
        return
    if len(path) < 2:
        return
    if not any(w in (host + path).lower() for w in KEEP):
        return
    sink.setdefault(host + path, "https://" + host + path)


def harvest(text, sink):
    for u in URL_RE.findall(text):
        add(u, sink)
    for d in DOM_RE.findall(text):
        add(d, sink, bare_ok=True)


def main():
    print("=" * 58)
    print("        S Y N C   S I T E S   v2")
    print("=" * 58)

    found = {}
    repos = []

    # ---------- 1. find repos ----------
    for q in QUERIES:
        try:
            data = get(f"https://api.github.com/search/repositories"
                       f"?q={q}&sort=stars&order=desc&per_page=20", as_json=True)
        except Exception as e:
            print(f"  x  search '{q}'  {type(e).__name__}")
            continue
        for it in data.get("items", []):
            full = it.get("full_name")
            if full and full not in [r[0] for r in repos]:
                repos.append((full, it.get("default_branch", "main")))
        print(f"  +  search '{q}'  -> {len(data.get('items', []))} repos")
        time.sleep(1)

    repos = repos[:MAX_REPOS]
    print(f"\n[*] digging into {len(repos)} repos...\n")

    # ---------- 2. dig into each repo ----------
    for full, branch in repos:
        try:
            tree = get(f"https://api.github.com/repos/{full}/git/trees/"
                       f"{branch}?recursive=1", as_json=True)
        except Exception as e:
            print(f"  x  {full}  {type(e).__name__}")
            continue

        cand = []
        for node in tree.get("tree", []):
            p = node.get("path", "")
            if not p.lower().endswith(GOOD_EXT):
                continue
            if node.get("size", 0) > 400000:
                continue
            name = p.split("/")[-1]
            if FILE_HINT.search(name):
                cand.append(p)
        cand = cand[:MAX_FILES_PER_REPO]

        got = 0
        for p in cand:
            try:
                txt = get(f"https://raw.githubusercontent.com/{full}/"
                          f"{branch}/{p}")
            except Exception:
                continue
            before = len(found)
            harvest(txt, found)
            got += len(found) - before
        print(f"  {'+' if got else 'x'}  {full:44} {got:5} new")

    # ---------- 3. direct sources ----------
    print()
    for src in DIRECT:
        try:
            txt = get(src)
        except Exception as e:
            print(f"  x  {src.split('/')[-1]:44} {type(e).__name__}")
            continue
        before = len(found)
        harvest(txt, found)
        print(f"  +  {src.split('/')[-1]:44} {len(found) - before:5} new")

    if not found:
        print("\n[X] nothing found. check your internet.")
        input("\nPress Enter to exit...")
        return

    urls = sorted(found.values(), key=lambda u: u.lower())
    print(f"\n[*] TOTAL unique endpoints: {len(urls)}")

    if os.path.exists(OUT) and not os.path.exists(BACKUP):
        os.rename(OUT, BACKUP)
        print("[*] old sites.txt saved as sites_backup.txt")

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("# auto-generated by sync_sites.py\n")
        f.write("# format: URL|METHOD|PAYLOAD   "
                "(a bare domain means: hunt the endpoint)\n\n")
        for u in urls:
            if "{phone}" in u:
                f.write(f"{u}|GET|\n")
            elif u.count("/") == 2:
                f.write(f"{u}\n")
            else:
                f.write(f'{u}|POST|{{"phone":"{{phone}}"}}\n')

    print(f"[*] wrote {len(urls)} lines to sites.txt")
    print("[*] delete alive.json if it exists, then run: python bomber.py")
    input("\nPress Enter to exit...")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nbye.")

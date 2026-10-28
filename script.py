import os
import re
import sys
import json
import time
from datetime import datetime, timezone
import requests
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK")
BBB_TOKEN = os.environ.get("BBB_TOKEN")  # token "Private" (builtbybit.com/account/api)
DRY_RUN = os.environ.get("DRY_RUN") == "1"
API_BASE = "https://api.builtbybit.com/v1"
SITE = "https://builtbybit.com"
CACHE_FILE = "last_versions.json"
LIST_FILE = "resources.txt"
HEADERS = {"User-Agent": "BBB-Check-Bot/1.0.0 (GitHub Actions)"}
if BBB_TOKEN:
    HEADERS["Authorization"] = f"Private {BBB_TOKEN}"
def http_get_json(url, retries=3):
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 404:
                return {}
            if r.status_code == 429:
                time.sleep(float(r.headers.get("Retry-After", 3)))
                continue
            if r.status_code >= 400:
                print(f"HTTP {r.status_code} ({url}): {r.text[:300]}")
                if r.status_code in (401, 403):
                    return None
            r.raise_for_status()
            body = r.json()
            if body.get("result") == "error":
                print(f"API error ({url}): {body.get('error')}")
                return None
            return body.get("data", body)
        except (requests.RequestException, ValueError) as e:
            print(f"Attempt {attempt}/{retries} ({url}): {e}")
            time.sleep(2 * attempt)
    return None
def load_ids():
    ids = []
    try:
        with open(LIST_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.split("#", 1)[0].strip()
                if not line:
                    continue
                m = re.fullmatch(r"\d+", line) or re.search(r"\.(\d+)(?:/|$|\?)", line) or re.search(r"/resources/(\d+)", line)
                if m:
                    rid = m.group(1) if m.lastindex else m.group(0)
                    if rid not in ids:
                        ids.append(rid)
                else:
                    print(f"Ligne ignorée (ID introuvable) : {line}")
    except FileNotFoundError:
        print(f"{LIST_FILE} introuvable.")
    return ids
def load_cache():
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, sort_keys=True)
        f.write("\n")
def version_id(v):
    return str(v.get("version_id") or v.get("id") or "")
def build_embed(rid, res, ver):
    title = res.get("title") or f"Resource {rid}"
    fields = [
        {"name": "🆔 Version", "value": f"`{ver.get('name', '?')}`", "inline": True},
        {"name": "🔗 Page", "value": f"[BuiltByBit]({SITE}/resources/{rid}/updates)", "inline": False},
    ]
    embed = {
        "title": f"🟢 {title.upper()} - New Version Detected",
        "url": f"{SITE}/resources/{rid}/updates",
        "color": 15844367,
        "fields": fields,
        "footer": {"text": "Plugin Update Checker - Automatic via GitHub"},
    }
    if res.get("tag_line"):
        embed["description"] = res["tag_line"][:200]
    ts = ver.get("release_date")
    if ts:
        try:
            embed["timestamp"] = datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
        except (ValueError, TypeError):
            pass
    return embed
def send_discord(embed):
    if DRY_RUN:
        print(json.dumps(embed, indent=2, ensure_ascii=False))
        return True
    for _ in range(3):
        try:
            res = requests.post(WEBHOOK_URL, json={"embeds": [embed]}, timeout=15)
        except requests.RequestException as e:
            print(f"Discord network error : {e}")
            time.sleep(2)
            continue
        if res.status_code == 429:
            time.sleep(float(res.json().get("retry_after", 2)))
            continue
        if res.status_code < 400:
            return True
        print(f"Discord failure : {res.status_code} - {res.text}")
        return False
    return False
def main():
    if not WEBHOOK_URL and not DRY_RUN:
        print("Error: DISCORD_WEBHOOK is missing.")
        sys.exit(1)
    if not BBB_TOKEN:
        print("Error: BBB_TOKEN is missing (token Private, builtbybit.com/account/api).")
        sys.exit(1)
    ids = load_ids()
    if not ids:
        print("Aucun ID dans resources.txt.")
        sys.exit(1)
    cache = load_cache()
    first_run = not cache
    failures = 0
    for rid in ids:
        ver = http_get_json(f"{API_BASE}/resources/{rid}/versions/latest")
        if ver is None:
            failures += 1
            continue
        if not ver:
            print(f"{rid}: no version found.")
            continue
        vid = version_id(ver)
        known = cache.get(rid)
        print(f"{rid} | API: {ver.get('name')} ({vid}) | Cache: {known or '-'}")
        if known == vid:
            continue
        if first_run or known is None:
            cache[rid] = vid
            continue
        res = http_get_json(f"{API_BASE}/resources/{rid}") or {}
        if send_discord(build_embed(rid, res, ver)):
            cache[rid] = vid
            print(f"Notification sent for {rid} {ver.get('name')}.")
        else:
            print(f"Send failed for {rid}: will retry on the next run.")
            failures += 1
        time.sleep(0.5)
    if not DRY_RUN:
        save_cache(cache)
    if failures:
        sys.exit(1)
if __name__ == "__main__":
    main()

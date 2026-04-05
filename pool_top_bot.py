import os
import json
import requests
from typing import List
from datetime import datetime, timezone

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

STATE_FILE = "state.json"
STATE_TTL_HOURS = 72

DEX_SEARCH_URL = "https://api.dexscreener.com/latest/dex/search"

MIN_LIQ = 50000
MIN_VOL = 5000

SURGE_MULT = 2.0
SURGE_MIN = 200000

NEW_LIQ = 200000
NEW_VOL = 50000


# ======================
# 유틸
# ======================
def now():
    return int(datetime.now(timezone.utc).timestamp())


def fmt(n):
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return f"{n:.0f}"


# ======================
# state (🔥 완전 안전)
# ======================
def load_state():
    if not os.path.exists(STATE_FILE):
        return {"pools": {}, "alerts": {}}

    try:
        with open(STATE_FILE, "r") as f:
            data = json.load(f)
    except:
        return {"pools": {}, "alerts": {}}

    if not isinstance(data, dict):
        return {"pools": {}, "alerts": {}}

    if "pools" not in data:
        data["pools"] = {}

    if "alerts" not in data:
        data["alerts"] = {}

    return data


def save_state(s):
    with open(STATE_FILE, "w") as f:
        json.dump(s, f, indent=2)


def cleanup_state(state):
    t = now()
    ttl = STATE_TTL_HOURS * 3600

    state["pools"] = {
        k: v for k, v in state["pools"].items()
        if t - v.get("last_seen", t) <= ttl
    }

    valid = set(state["pools"].keys())
    state["alerts"] = {
        k: v for k, v in state["alerts"].items()
        if k.split(":")[0] in valid
    }


def already_alerted(state, key, typ):
    return state["alerts"].get(f"{key}:{typ}", False)


def mark_alerted(state, key, typ):
    state["alerts"][f"{key}:{typ}"] = True


# ======================
# 텔레그램
# ======================
def send(msg):
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TG_CHAT_ID, "text": msg})


# ======================
# 데이터
# ======================
def fetch():
    keywords = ["USDT", "WETH", "WBTC", "BNB"]

    out = []

    for kw in keywords:
        try:
            data = requests.get(DEX_SEARCH_URL, params={"q": kw}).json()
        except:
            continue

        for p in data.get("pairs", []):
            liq = float(p.get("liquidity", {}).get("usd", 0))
            vol = float(p.get("volume", {}).get("h24", 0))

            if liq < MIN_LIQ or vol < MIN_VOL:
                continue

            out.append({
                "pair": f"{p['baseToken']['symbol']}/{p['quoteToken']['symbol']}",
                "liq": liq,
                "vol": vol,
                "url": p.get("url"),
                "key": p.get("pairAddress")
            })

    return out


# ======================
# 알림
# ======================
def detect(pools, state):
    alerts = []

    for p in pools:
        key = p["key"]
        prev = state["pools"].get(key, {})

        prev_liq = prev.get("liq", 0)
        curr = p["liq"]

        # 급증
        if prev_liq >= 100000 and curr >= prev_liq * SURGE_MULT and curr - prev_liq >= SURGE_MIN:
            if not already_alerted(state, key, "surge"):
                alerts.append(f"🚀 {p['pair']} 급증 {fmt(prev_liq)} → {fmt(curr)}\n{p['url']}")
                mark_alerted(state, key, "surge")

        # 신규
        if key not in state["pools"]:
            if p["liq"] >= NEW_LIQ and p["vol"] >= NEW_VOL:
                if not already_alerted(state, key, "new"):
                    alerts.append(f"🆕 {p['pair']} 신규\n{p['url']}")
                    mark_alerted(state, key, "new")

    return alerts


# ======================
# 상태 업데이트
# ======================
def update(pools, state):
    t = now()

    for p in pools:
        state["pools"][p["key"]] = {
            "liq": p["liq"],
            "last_seen": t
        }


# ======================
# 메인
# ======================
def main():
    state = load_state()

    pools = fetch()
    alerts = detect(pools, state)

    update(pools, state)
    cleanup_state(state)
    save_state(state)

    if not alerts:
        return

    msg = "\n\n".join(alerts)
    send(msg)


if __name__ == "__main__":
    main()

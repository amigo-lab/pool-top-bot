import os
import re
import json
import requests
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

TOP_N = 5
REQUEST_TIMEOUT = 30
STATE_FILE = "state.json"
STATE_TTL_HOURS = 72  # state 보관 기간 (3일)

GECKO_URL = "https://api.geckoterminal.com/api/v2/networks/{chain}/pools"
DEX_SEARCH_URL = "https://api.dexscreener.com/latest/dex/search"

STABLES = {"USDT", "USDC", "DAI", "BUSD", "FDUSD", "USDT0", "TUSD"}
MAJORS = {"BTC", "WBTC", "BTCB", "ETH", "WETH", "BNB", "WBNB", "MATIC", "WMATIC", "POL", "WPOL"}

BAD_KEYWORDS = {
    "doge", "inu", "baby", "pepe", "shib", "cat", "elon",
    "banana", "bananas", "frog", "moon", "pump", "siren"
}

STABLE_ALIASES = {
    "USDT0": "USDT",
    "USD+": "USDT",
    "USDC.E": "USDC",
    "USDT.E": "USDT",
}

NETWORKS = {
    "polygon_pos": {
        "label": "Polygon",
        "dex_chain": "polygon",
        "keywords": ["LGNS","DAI","USDT","USDC","WETH","WBTC","MATIC"],
    },
    "bsc": {
        "label": "BSC",
        "dex_chain": "bsc",
        "keywords": ["WBNB","BNB","BTCB","USDT","USDC"],
    },
}

MIN_LIQUIDITY_DEFAULT = 50_000
MIN_VOLUME_DEFAULT = 5_000

MIN_LIQUIDITY_BSC = 500_000
MIN_VOLUME_BSC = 50_000

SURGE_MIN_PREV_LIQ = 100_000
SURGE_MIN_ABS_DELTA = 200_000
SURGE_MULTIPLIER = 2.0

NEW_MIN_LIQ = 200_000
NEW_MIN_VOL = 50_000
NEW_MAX_AGE_HOURS = 24


# ======================
# 텔레그램
# ======================
def send_telegram_message(text: str) -> None:
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TG_CHAT_ID, "text": text})


def split_message(text: str, size=3500):
    return [text[i:i+size] for i in range(0, len(text), size)]


# ======================
# 유틸
# ======================
def to_float(v, d=0.0):
    try:
        return float(v)
    except:
        return d


def fmt(n):
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return f"{n:.0f}"


def now():
    return int(datetime.now(timezone.utc).timestamp())


# ======================
# state
# ======================
def load_state():
    if not os.path.exists(STATE_FILE):
        return {"pools": {}, "alerts": {}}
    return json.load(open(STATE_FILE))


def save_state(s):
    json.dump(s, open(STATE_FILE, "w"), indent=2)


def cleanup_state(state):
    ttl = STATE_TTL_HOURS * 3600
    t = now()

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
# 필터
# ======================
def valid_pair(a, b):
    if a in STABLES and b in STABLES:
        return False
    if a in MAJORS and b in MAJORS:
        return False
    return True


# ======================
# 데이터 수집
# ======================
def fetch_dex(chain, keywords):
    out = []

    for kw in keywords:
        try:
            data = requests.get(DEX_SEARCH_URL, params={"q": kw}).json()
        except:
            continue

        for p in data.get("pairs", []):
            if p.get("chainId") != chain:
                continue

            base = p["baseToken"]["symbol"]
            quote = p["quoteToken"]["symbol"]

            liq = to_float(p["liquidity"]["usd"])
            vol = to_float(p["volume"]["h24"])

            if liq < MIN_LIQUIDITY_DEFAULT or vol < MIN_VOLUME_DEFAULT:
                continue

            if not valid_pair(base, quote):
                continue

            out.append({
                "pair": f"{base}/{quote}",
                "dex": p["dexId"],
                "liq": liq,
                "vol": vol,
                "url": p["url"],
                "key": p["pairAddress"]
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
        if (
            prev_liq >= SURGE_MIN_PREV_LIQ and
            curr >= prev_liq * SURGE_MULTIPLIER and
            curr - prev_liq >= SURGE_MIN_ABS_DELTA
        ):
            if not already_alerted(state, key, "surge"):
                alerts.append(f"🚀 {p['pair']} 급증 {fmt(prev_liq)} → {fmt(curr)}\n{p['url']}")
                mark_alerted(state, key, "surge")

        # 신규
        if key not in state["pools"]:
            if p["liq"] >= NEW_MIN_LIQ and p["vol"] >= NEW_MIN_VOL:
                if not already_alerted(state, key, "new"):
                    alerts.append(f"🆕 {p['pair']} 신규\n{p['url']}")
                    mark_alerted(state, key, "new")

    return alerts


# ======================
# 상태 업데이트
# ======================
def update_state(pools, state):
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

    all_pools = []

    for chain, cfg in NETWORKS.items():
        pools = fetch_dex(cfg["dex_chain"], cfg["keywords"])
        all_pools.extend(pools)

    alerts = detect(all_pools, state)

    update_state(all_pools, state)
    cleanup_state(state)
    save_state(state)

    # ⭐ 알림 없으면 안 보냄
    if not alerts:
        return

    msg = "\n\n".join(alerts)

    for chunk in split_message(msg):
        send_telegram_message(chunk)


if __name__ == "__main__":
    main()

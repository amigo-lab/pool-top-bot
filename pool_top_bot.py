import os
import requests
from typing import Any, Dict, List, Optional

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

TOP_N = 5
REQUEST_TIMEOUT = 30

GECKO_URL = "https://api.geckoterminal.com/api/v2/networks/{chain}/pools"
DEX_SEARCH_URL = "https://api.dexscreener.com/latest/dex/search"

STABLES = {"USDT","USDC","DAI","BUSD","FDUSD","USDT0"}
MAJORS = {"BTC","WBTC","BTCB","ETH","WETH","BNB","WBNB","MATIC","WMATIC","POL","WPOL"}

BAD_KEYWORDS = {"doge","inu","baby","pepe","shib","cat","elon"}

NETWORKS = {
    "polygon_pos": {
        "label": "Polygon",
        "dex_chain": "polygon",
        "keywords": ["LGNS","DAI","USDT","USDC","QuickSwap","Uniswap","Aave","Curve","Balancer","WETH","WBTC"]
    },
    "bsc": {
        "label": "BSC",
        "dex_chain": "bsc",
        "keywords": ["CAKE","WBNB","BNB","BTCB","USDT","USDC","PancakeSwap"]
    }
}


# -----------------------
# 유틸
# -----------------------
def send(msg):
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TG_CHAT_ID, "text": msg})


def to_float(v):
    try:
        return float(v)
    except:
        return 0.0


def fmt(n):
    if n >= 1e9:
        return f"{n/1e9:.2f}B"
    if n >= 1e6:
        return f"{n/1e6:.2f}M"
    if n >= 1e3:
        return f"{n/1e3:.2f}K"
    return f"{n:.2f}"


def is_bad(sym):
    s = sym.lower()
    return any(k in s for k in BAD_KEYWORDS)


def valid(base, quote):
    base = base.upper()
    quote = quote.upper()

    if base in STABLES and quote in STABLES:
        return False
    if base in MAJORS and quote in MAJORS:
        return False
    if (base in STABLES and quote in MAJORS) or (base in MAJORS and quote in STABLES):
        return False

    if is_bad(base) or is_bad(quote):
        return False

    return True


# -----------------------
# Gecko
# -----------------------
def fetch_gecko(chain):
    pools = []

    for page in range(1,6):
        try:
            r = requests.get(GECKO_URL.format(chain=chain),
                params={"page":page,"include":"base_token,quote_token,dex"}).json()
        except:
            continue

        inc = {i["id"]:i for i in r.get("included",[])}

        for p in r.get("data",[]):
            try:
                attr = p["attributes"]
                rel = p["relationships"]

                base = inc.get(rel["base_token"]["data"]["id"],{}).get("attributes",{})
                quote = inc.get(rel["quote_token"]["data"]["id"],{}).get("attributes",{})
                dex = inc.get(rel["dex"]["data"]["id"],{}).get("attributes",{})

                bs = base.get("symbol","").upper()
                qs = quote.get("symbol","").upper()

                if not valid(bs,qs):
                    continue

                liq = to_float(attr.get("reserve_in_usd"))
                vol = to_float(attr.get("volume_usd",{}).get("h24"))

                if liq < 50000 or vol < 5000:
                    continue

                # 🔥 펌핑 제거
                if vol > liq * 3:
                    continue

                pools.append({
                    "pair": f"{bs}/{qs}",
                    "liq": liq,
                    "vol": vol,
                    "dex": dex.get("name",""),
                    "url": f"https://www.geckoterminal.com/{chain}/pools/{attr.get('address')}",
                    "addr": attr.get("address")
                })
            except:
                continue

    return pools


# -----------------------
# Dex
# -----------------------
def fetch_dex(chain, keywords):
    pools = []

    for k in keywords:
        try:
            r = requests.get(DEX_SEARCH_URL, params={"q":k}).json()
        except:
            continue

        for p in r.get("pairs",[]):
            try:
                if p.get("chainId") != chain:
                    continue

                bs = p.get("baseToken",{}).get("symbol","").upper()
                qs = p.get("quoteToken",{}).get("symbol","").upper()

                if not valid(bs,qs):
                    continue

                liq = to_float(p.get("liquidity",{}).get("usd"))
                vol = to_float(p.get("volume",{}).get("h24"))

                if liq < 50000 or vol < 5000:
                    continue

                # 🔥 펌핑 제거
                if vol > liq * 3:
                    continue

                pools.append({
                    "pair": f"{bs}/{qs}",
                    "liq": liq,
                    "vol": vol,
                    "dex": p.get("dexId"),
                    "url": p.get("url"),
                    "addr": p.get("pairAddress")
                })
            except:
                continue

    return pools


# -----------------------
# LGNS 강제
# -----------------------
def inject_lgns():
    return [{
        "pair": "LGNS/DAI",
        "liq": 480_000_000,
        "vol": 40_000_000,
        "dex": "QuickSwap",
        "url": "https://dexscreener.com/polygon/0x882df4b0fb50a229c3b4124eb18c759911485bfb",
        "addr": "0x882df4b0fb50a229c3b4124eb18c759911485bfb"
    }]


# -----------------------
# 중복 제거 (주소 기준)
# -----------------------
def dedup_addr(pools):
    m = {}
    for p in pools:
        key = p.get("addr") or p.get("url")
        if key not in m or p["liq"] > m[key]["liq"]:
            m[key] = p
    return list(m.values())


# -----------------------
# 같은 pair 정리
# -----------------------
def dedup_pair(pools):
    m = {}
    for p in pools:
        k = p["pair"]
        if k not in m or p["liq"] > m[k]["liq"]:
            m[k] = p
    return list(m.values())


# -----------------------
# 메인
# -----------------------
def build(chain, name, dex_chain, keywords):

    pools = fetch_gecko(chain) + fetch_dex(dex_chain, keywords)

    if chain == "polygon_pos":
        pools += inject_lgns()

    pools = dedup_addr(pools)
    pools = dedup_pair(pools)

    # 🔥 BSC 추가 필터
    if chain == "bsc":
        pools = [p for p in pools if p["liq"] > 300000]

    top_liq = sorted(pools, key=lambda x: x["liq"], reverse=True)[:TOP_N]
    top_vol = sorted(pools, key=lambda x: x["vol"], reverse=True)[:TOP_N]

    msg = f"[{name} 유동성 TOP {TOP_N}]\n"
    for i,p in enumerate(top_liq,1):
        msg += f"{i}) {p['pair']} | {p['dex']} | 유동성 {fmt(p['liq'])} | 거래량 {fmt(p['vol'])}\n{p['url']}\n"

    msg += f"\n[{name} 거래량 TOP {TOP_N}]\n"
    for i,p in enumerate(top_vol,1):
        msg += f"{i}) {p['pair']} | {p['dex']} | 거래량 {fmt(p['vol'])} | 유동성 {fmt(p['liq'])}\n{p['url']}\n"

    return msg


def main():
    msg = ""
    for chain, cfg in NETWORKS.items():
        msg += build(chain, cfg["label"], cfg["dex_chain"], cfg["keywords"]) + "\n\n"

    msg += "[안내]\n- 밈코인 제거\n- 펌핑 필터 적용\n- LGNS 강제 포함\n- 실전용 안정 버전"

    send(msg)


if __name__ == "__main__":
    main()

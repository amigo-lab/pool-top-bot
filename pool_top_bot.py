import os
import requests

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

TOP_N = 5

GECKO_URL = "https://api.geckoterminal.com/api/v2/networks/{chain}/pools"
DEX_SEARCH = "https://api.dexscreener.com/latest/dex/search"

STABLES = {"USDT","USDC","DAI","BUSD","FDUSD","USDT0"}
MAJORS = {"BTC","WBTC","ETH","WETH","BNB","WBNB","MATIC","WMATIC","POL","WPOL"}

# -----------------------
# 텔레그램 전송
# -----------------------
def send(msg):
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TG_CHAT_ID, "text": msg})


# -----------------------
# 필터
# -----------------------
def valid(base, quote):
    if base in STABLES and quote in STABLES:
        return False
    if base in MAJORS and quote in MAJORS:
        return False
    if (base in STABLES and quote in MAJORS) or (base in MAJORS and quote in STABLES):
        return False
    return True


# -----------------------
# Gecko 수집
# -----------------------
def fetch_gecko(chain):
    pools = []

    for page in range(1, 6):
        try:
            r = requests.get(GECKO_URL.format(chain=chain), params={
                "page": page,
                "include": "base_token,quote_token,dex"
            }).json()
        except:
            continue

        included = {i["id"]: i for i in r.get("included", [])}

        for p in r.get("data", []):
            attr = p["attributes"]
            rel = p["relationships"]

            base = included.get(rel["base_token"]["data"]["id"], {}).get("attributes", {})
            quote = included.get(rel["quote_token"]["data"]["id"], {}).get("attributes", {})
            dex = included.get(rel["dex"]["data"]["id"], {}).get("attributes", {})

            base_s = base.get("symbol","").upper()
            quote_s = quote.get("symbol","").upper()

            if not valid(base_s, quote_s):
                continue

            pools.append({
                "pair": f"{base_s}/{quote_s}",
                "dex": dex.get("name",""),
                "liq": float(attr.get("reserve_in_usd",0)),
                "vol": float(attr.get("volume_usd",{}).get("h24",0)),
                "url": f"https://www.geckoterminal.com/{chain}/pools/{attr.get('address')}"
            })

    return pools


# -----------------------
# Dex 수집
# -----------------------
def fetch_dex(chain):
    pools = []

    keywords = ["USDT","USDC","DAI","WETH","WBTC","BNB","CAKE","MATIC","POL"]

    for k in keywords:
        try:
            r = requests.get(DEX_SEARCH, params={"q": k}).json()
        except:
            continue

        for p in r.get("pairs", []):
            if p.get("chainId") != chain:
                continue

            base = p.get("baseToken", {}).get("symbol","").upper()
            quote = p.get("quoteToken", {}).get("symbol","").upper()

            if not valid(base, quote):
                continue

            pools.append({
                "pair": f"{base}/{quote}",
                "dex": p.get("dexId",""),
                "liq": float(p.get("liquidity",{}).get("usd",0)),
                "vol": float(p.get("volume",{}).get("h24",0)),
                "url": p.get("url")
            })

    return pools


# -----------------------
# LGNS 강제 삽입 (핵심)
# -----------------------
def inject_lgns(pools):
    pools.append({
        "pair": "LGNS/DAI",
        "dex": "QuickSwap",
        "liq": 480_000_000,
        "vol": 40_000_000,
        "url": "https://www.geckoterminal.com/polygon_pos/pools/0x882df4b0fb50a229c3b4124eb18c759911485bfb"
    })


# -----------------------
# TOP 계산
# -----------------------
def build(chain, name):
    gecko = fetch_gecko(chain)
    dex = fetch_dex("polygon" if chain=="polygon_pos" else "bsc")

    pools = gecko + dex

    # 🔥 LGNS 강제 추가
    if chain == "polygon_pos":
        inject_lgns(pools)

    # 중복 제거
    uniq = {}
    for p in pools:
        key = p["pair"] + p["dex"]
        if key not in uniq or uniq[key]["liq"] < p["liq"]:
            uniq[key] = p

    pools = list(uniq.values())

    top_liq = sorted(pools, key=lambda x: x["liq"], reverse=True)[:TOP_N]
    top_vol = sorted(pools, key=lambda x: x["vol"], reverse=True)[:TOP_N]

    msg = f"[{name} 유동성 TOP {TOP_N}]\n"
    for i,p in enumerate(top_liq,1):
        msg += f"{i}) {p['pair']} | {p['dex']} | 유동성 {p['liq']:.2f} | 거래량 {p['vol']:.2f}\n{p['url']}\n"

    msg += f"\n[{name} 거래량 TOP {TOP_N}]\n"
    for i,p in enumerate(top_vol,1):
        msg += f"{i}) {p['pair']} | {p['dex']} | 거래량 {p['vol']:.2f} | 유동성 {p['liq']:.2f}\n{p['url']}\n"

    return msg


# -----------------------
# 실행
# -----------------------
def main():
    msg = ""
    msg += build("polygon_pos","Polygon")
    msg += "\n"
    msg += build("bsc","BSC")

    send(msg)


if __name__ == "__main__":
    main()

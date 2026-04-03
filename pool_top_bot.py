import os
import requests

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

STABLES = {"USDT", "USDC", "DAI", "BUSD", "USDT0", "TUSD"}
MAJORS = {"WBTC", "BTCB", "WETH", "ETH", "WPOL", "MATIC"}

def send(msg):
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TG_CHAT_ID, "text": msg})

def is_excluded(base, quote):
    return (base in STABLES and quote in STABLES) or \
           (base in MAJORS and quote in MAJORS)

def fetch_gecko(chain):
    url = f"https://api.geckoterminal.com/api/v2/networks/{chain}/pools"
    params = {
        "sort": "liquidity_desc",
        "page": 1
    }
    r = requests.get(url, params=params, timeout=30).json()
    return r.get("data", [])

def parse_pool(p):
    attr = p["attributes"]
    base = attr["base_token_symbol"]
    quote = attr["quote_token_symbol"]

    return {
        "pair": f"{base}/{quote}",
        "base": base,
        "quote": quote,
        "liquidity": float(attr.get("reserve_in_usd", 0)),
        "volume": float(attr.get("volume_usd", {}).get("h24", 0)),
        "dex": attr.get("dex_name"),
        "url": f"https://www.geckoterminal.com/{p['relationships']['network']['data']['id']}/pools/{p['id'].split('_')[-1]}"
    }

def build_top10(chain):
    raw = fetch_gecko(chain)
    pools = []

    seen = set()

    for p in raw:
        pool = parse_pool(p)
        addr = p["id"]

        if addr in seen:
            continue
        seen.add(addr)

        if is_excluded(pool["base"], pool["quote"]):
            continue

        pools.append(pool)

    top_liq = sorted(pools, key=lambda x: x["liquidity"], reverse=True)[:10]
    top_vol = sorted(pools, key=lambda x: x["volume"], reverse=True)[:10]

    return top_liq, top_vol

def format_msg(title, data, key):
    msg = f"[{title}]\n"
    for i, d in enumerate(data, 1):
        msg += f"{i}) {d['pair']} | {d['dex']} | 유동성 ${d['liquidity']:.2f} | 거래량 ${d['volume']:.2f}\n"
    return msg

def main():
    chains = {
        "polygon_pos": "Polygon",
        "bsc": "BSC"
    }

    final_msg = ""

    for chain_id, name in chains.items():
        liq, vol = build_top10(chain_id)

        final_msg += format_msg(f"{name} 유동성 TOP10", liq, "liquidity")
        final_msg += "\n"
        final_msg += format_msg(f"{name} 거래량 TOP10", vol, "volume")
        final_msg += "\n\n"

    send(final_msg)

if __name__ == "__main__":
    main()

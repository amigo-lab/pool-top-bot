import os
import requests
from typing import Any, Dict, List, Optional

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

TOP_N = 5
REQUEST_TIMEOUT = 30

GECKO_URL = "https://api.geckoterminal.com/api/v2/networks/{chain}/pools"
DEX_SEARCH_URL = "https://api.dexscreener.com/latest/dex/search"

STABLES = {"USDT", "USDC", "DAI", "BUSD", "FDUSD", "USDT0", "USD1"}
MAJORS = {"BTC", "WBTC", "BTCB", "ETH", "WETH", "BNB", "WBNB", "MATIC", "WMATIC", "POL", "WPOL"}

NETWORKS = {
    "polygon_pos": {
        "label": "Polygon",
        "dex_chain": "polygon",
        "search_keywords": [
            "LGNS",
            "Longinus",
            "DAI",
            "USDT",
            "USDC",
            "QuickSwap",
            "Uniswap",
            "Aave",
            "Curve",
            "Balancer",
            "Sushi",
            "WETH",
            "WBTC",
            "POL",
            "WPOL",
            "MATIC",
        ],
        "max_same_base_in_top": 2,
    },
    "bsc": {
        "label": "BSC",
        "dex_chain": "bsc",
        "search_keywords": [
            "CAKE",
            "WBNB",
            "BNB",
            "BTCB",
            "USDT",
            "USDC",
            "FDUSD",
            "BUSD",
            "PancakeSwap",
            "THENA",
            "Venus",
            "Lista",
        ],
        "max_same_base_in_top": 1,
    },
}


def send_telegram_message(text: str) -> None:
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        raise ValueError("TG_BOT_TOKEN 또는 TG_CHAT_ID가 없습니다.")

    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }
    r = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def fmt_num(value: Optional[float]) -> str:
    if value is None:
        return "-"
    n = float(value)
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.2f}K"
    if n >= 1:
        return f"{n:.2f}"
    return f"{n:.6f}"


def split_message(text: str, chunk_size: int = 3500) -> List[str]:
    if len(text) <= chunk_size:
        return [text]

    chunks: List[str] = []
    current = ""

    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > chunk_size:
            if current:
                chunks.append(current.rstrip())
            current = line
        else:
            current += line

    if current:
        chunks.append(current.rstrip())

    return chunks


def valid_pair(base: str, quote: str) -> bool:
    base = (base or "").upper()
    quote = (quote or "").upper()

    if not base or not quote:
        return False

    if base in STABLES and quote in STABLES:
        return False

    if base in MAJORS and quote in MAJORS:
        return False

    if (base in STABLES and quote in MAJORS) or (base in MAJORS and quote in STABLES):
        return False

    return True


def normalize_pool(row: Dict[str, Any]) -> Dict[str, Any]:
    row["pair"] = row.get("pair", "-")
    row["base_symbol"] = (row.get("base_symbol") or "").upper()
    row["quote_symbol"] = (row.get("quote_symbol") or "").upper()
    row["dex"] = row.get("dex") or "-"
    row["liq"] = to_float(row.get("liq"), 0.0)
    row["vol"] = to_float(row.get("vol"), 0.0)
    row["url"] = row.get("url") or "-"
    row["pool_address"] = (row.get("pool_address") or "").lower()
    return row


def extract_pool_address_from_url(url: str) -> str:
    if not url:
        return ""
    try:
        return url.rstrip("/").split("/")[-1].lower()
    except Exception:
        return ""


def unique_key(pool: Dict[str, Any]) -> str:
    if pool.get("pool_address"):
        return pool["pool_address"]
    extracted = extract_pool_address_from_url(pool.get("url", ""))
    if extracted:
        return extracted
    return f"{pool.get('pair','')}_{pool.get('dex','')}".lower()


def merge_pools(pools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    uniq: Dict[str, Dict[str, Any]] = {}

    for raw in pools:
        p = normalize_pool(raw)
        key = unique_key(p)

        if key not in uniq:
            uniq[key] = p
            continue

        old = uniq[key]

        if p["liq"] > old["liq"]:
            uniq[key] = p
            continue

        if p["liq"] == old["liq"] and p["vol"] > old["vol"]:
            uniq[key] = p
            continue

        if old.get("url") in {"", "-"} and p.get("url") not in {"", "-"}:
            old["url"] = p["url"]
        if not old.get("pool_address") and p.get("pool_address"):
            old["pool_address"] = p["pool_address"]

    return list(uniq.values())


def deduplicate_same_pair(pools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}

    for p in pools:
        pair_key = (p.get("pair") or "").upper()
        if not pair_key:
            continue

        if pair_key not in result:
            result[pair_key] = p
            continue

        if p["liq"] > result[pair_key]["liq"]:
            result[pair_key] = p
            continue

        if p["liq"] == result[pair_key]["liq"] and p["vol"] > result[pair_key]["vol"]:
            result[pair_key] = p

    return list(result.values())


def diversify_by_base_symbol(
    pools: List[Dict[str, Any]],
    top_n: int,
    max_same_base: int
) -> List[Dict[str, Any]]:
    selected: List[Dict[str, Any]] = []
    base_count: Dict[str, int] = {}

    for p in pools:
        base = (p.get("base_symbol") or "").upper()
        count = base_count.get(base, 0)

        if count >= max_same_base:
            continue

        selected.append(p)
        base_count[base] = count + 1

        if len(selected) >= top_n:
            break

    # 만약 필터 때문에 개수가 모자라면 남은 후보로 채움
    if len(selected) < top_n:
        used_urls = {x.get("url") for x in selected}
        for p in pools:
            if p.get("url") in used_urls:
                continue
            selected.append(p)
            used_urls.add(p.get("url"))
            if len(selected) >= top_n:
                break

    return selected


def fetch_gecko(chain: str) -> List[Dict[str, Any]]:
    pools: List[Dict[str, Any]] = []

    for page in range(1, 6):
        try:
            r = requests.get(
                GECKO_URL.format(chain=chain),
                params={"page": page, "include": "base_token,quote_token,dex"},
                timeout=REQUEST_TIMEOUT,
            )
            data = r.json()
        except Exception:
            continue

        included = {item.get("id"): item for item in data.get("included", [])}

        for p in data.get("data", []):
            try:
                attr = p.get("attributes", {})
                rel = p.get("relationships", {})

                base_id = rel.get("base_token", {}).get("data", {}).get("id")
                quote_id = rel.get("quote_token", {}).get("data", {}).get("id")
                dex_id = rel.get("dex", {}).get("data", {}).get("id")

                base = included.get(base_id, {}).get("attributes", {})
                quote = included.get(quote_id, {}).get("attributes", {})
                dex = included.get(dex_id, {}).get("attributes", {})

                base_s = (base.get("symbol") or "").upper()
                quote_s = (quote.get("symbol") or "").upper()

                if not valid_pair(base_s, quote_s):
                    continue

                address = (attr.get("address") or "").lower()
                volume_h24 = to_float((attr.get("volume_usd") or {}).get("h24"), 0.0)
                liquidity = to_float(attr.get("reserve_in_usd"), 0.0)

                if liquidity < 50_000:
                    continue
                if volume_h24 < 5_000:
                    continue

                pools.append({
                    "pair": f"{base_s}/{quote_s}",
                    "base_symbol": base_s,
                    "quote_symbol": quote_s,
                    "dex": dex.get("name", "-"),
                    "liq": liquidity,
                    "vol": volume_h24,
                    "pool_address": address,
                    "url": f"https://www.geckoterminal.com/{chain}/pools/{address}" if address else "-",
                })
            except Exception:
                continue

    return pools


def fetch_dex(chain: str, keywords: List[str]) -> List[Dict[str, Any]]:
    pools: List[Dict[str, Any]] = []

    for keyword in keywords:
        try:
            r = requests.get(
                DEX_SEARCH_URL,
                params={"q": keyword},
                timeout=REQUEST_TIMEOUT,
            )
            data = r.json()
        except Exception:
            continue

        for p in data.get("pairs", []):
            try:
                if (p.get("chainId") or "").lower() != chain.lower():
                    continue

                base = p.get("baseToken", {}) or {}
                quote = p.get("quoteToken", {}) or {}

                base_s = (base.get("symbol") or "").upper()
                quote_s = (quote.get("symbol") or "").upper()

                if not valid_pair(base_s, quote_s):
                    continue

                liquidity = to_float((p.get("liquidity") or {}).get("usd"), 0.0)
                volume_h24 = to_float((p.get("volume") or {}).get("h24"), 0.0)

                if liquidity < 50_000:
                    continue
                if volume_h24 < 5_000:
                    continue

                pools.append({
                    "pair": f"{base_s}/{quote_s}",
                    "base_symbol": base_s,
                    "quote_symbol": quote_s,
                    "dex": p.get("dexId", "-"),
                    "liq": liquidity,
                    "vol": volume_h24,
                    "pool_address": (p.get("pairAddress") or "").lower(),
                    "url": p.get("url") or "-",
                })
            except Exception:
                continue

    return pools


def inject_lgns_manual() -> List[Dict[str, Any]]:
    return [{
        "pair": "LGNS/DAI",
        "base_symbol": "LGNS",
        "quote_symbol": "DAI",
        "dex": "QuickSwap",
        "liq": 480_000_000,
        "vol": 40_000_000,
        "pool_address": "0x882df4b0fb50a229c3b4124eb18c759911485bfb",
        "url": "https://www.geckoterminal.com/polygon_pos/pools/0x882df4b0fb50a229c3b4124eb18c759911485bfb",
    }]


def build(chain: str, name: str, dex_chain: str, keywords: List[str], max_same_base_in_top: int) -> str:
    gecko_pools = fetch_gecko(chain)
    dex_pools = fetch_dex(dex_chain, keywords)

    all_pools = gecko_pools + dex_pools

    if chain == "polygon_pos":
        all_pools += inject_lgns_manual()

    pools = merge_pools(all_pools)
    pools = deduplicate_same_pair(pools)

    liq_sorted = sorted(pools, key=lambda x: (x["liq"], x["vol"]), reverse=True)
    vol_sorted = sorted(pools, key=lambda x: (x["vol"], x["liq"]), reverse=True)

    top_liq = diversify_by_base_symbol(liq_sorted, TOP_N, max_same_base_in_top)
    top_vol = diversify_by_base_symbol(vol_sorted, TOP_N, max_same_base_in_top)

    lines: List[str] = []

    lines.append(f"[{name} 유동성 TOP {TOP_N}]")
    if top_liq:
        for i, p in enumerate(top_liq, 1):
            lines.append(
                f"{i}) {p['pair']} | {p['dex']} | 유동성 {fmt_num(p['liq'])} | 거래량 {fmt_num(p['vol'])}"
            )
            lines.append(f"{p['url']}")
    else:
        lines.append("- 후보 없음")

    lines.append("")
    lines.append(f"[{name} 거래량 TOP {TOP_N}]")
    if top_vol:
        for i, p in enumerate(top_vol, 1):
            lines.append(
                f"{i}) {p['pair']} | {p['dex']} | 거래량 {fmt_num(p['vol'])} | 유동성 {fmt_num(p['liq'])}"
            )
            lines.append(f"{p['url']}")
    else:
        lines.append("- 후보 없음")

    return "\n".join(lines)


def main() -> None:
    messages: List[str] = []

    for chain, cfg in NETWORKS.items():
        messages.append(
            build(
                chain=chain,
                name=cfg["label"],
                dex_chain=cfg["dex_chain"],
                keywords=cfg["search_keywords"],
                max_same_base_in_top=cfg["max_same_base_in_top"],
            )
        )

    messages.append("[안내]")
    messages.append("- Gecko + DexScreener 무료 조합 버전")
    messages.append("- 중복 제거는 pool_address 기준")
    messages.append("- 같은 pair는 가장 큰 유동성 1개만 유지")
    messages.append("- BSC는 같은 base 토큰 반복 노출을 줄이도록 보정")
    messages.append("- LGNS 대표 풀은 강제 포함 후 중복 제거")

    final_message = "\n\n".join(messages)

    for chunk in split_message(final_message):
        send_telegram_message(chunk)


if __name__ == "__main__":
    main()

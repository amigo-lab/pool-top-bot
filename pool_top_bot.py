import os
import math
import requests
from typing import Any, Dict, List, Optional, Tuple

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
GECKO_API_KEY = os.getenv("GECKO_API_KEY", "").strip()

GECKO_BASE_URL = "https://api.geckoterminal.com/api/v2"
REQUEST_TIMEOUT = 30

# 무료 환경 기준으로 너무 많이 때리지 않도록 보수적으로 설정
# Top pools by network 는 page를 지원하며 페이지당 최대 20개 풀을 반환합니다.
FETCH_PAGES = 5

NETWORKS = {
    "polygon_pos": "Polygon",
    "bsc": "BSC",
}

STABLES = {
    "USDT", "USDC", "USDC.E", "USDT.E", "USDT0", "DAI", "BUSD", "FDUSD", "TUSD",
    "USDP", "USDD", "MAI",
}

MAJORS = {
    "BTC", "WBTC", "BTCB",
    "ETH", "WETH",
    "BNB", "WBNB",
    "MATIC", "WMATIC", "POL", "WPOL",
}

BAD_KEYWORDS = {
    "doge", "inu", "baby", "banana", "pepe", "elon", "cat", "shib", "meme"
}


def gecko_headers() -> Dict[str, str]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "pool-top-bot/1.0",
    }
    if GECKO_API_KEY:
        headers["x-cg-pro-api-key"] = GECKO_API_KEY
    return headers


def fmt_num(value: Optional[float]) -> str:
    if value is None:
        return "-"
    num = float(value)
    if num >= 1_000_000_000:
        return f"{num / 1_000_000_000:.2f}B"
    if num >= 1_000_000:
        return f"{num / 1_000_000:.2f}M"
    if num >= 1_000:
        return f"{num / 1_000:.2f}K"
    if num >= 1:
        return f"{num:.2f}"
    return f"{num:.6f}"


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (ValueError, TypeError):
        return default


def is_bad_name(text: str) -> bool:
    s = (text or "").lower()
    return any(k in s for k in BAD_KEYWORDS)


def is_excluded_pair(base_symbol: str, quote_symbol: str) -> bool:
    base_symbol = (base_symbol or "").upper()
    quote_symbol = (quote_symbol or "").upper()

    both_stables = base_symbol in STABLES and quote_symbol in STABLES
    both_majors = base_symbol in MAJORS and quote_symbol in MAJORS
    stable_major_mix = (
        (base_symbol in STABLES and quote_symbol in MAJORS) or
        (base_symbol in MAJORS and quote_symbol in STABLES)
    )
    return both_stables or both_majors or stable_major_mix


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


def request_json(url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    r = requests.get(url, params=params, headers=gecko_headers(), timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict):
        raise ValueError("API 응답 형식이 예상과 다릅니다.")
    return data


def build_included_map(included: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    for item in included or []:
        item_id = item.get("id")
        if item_id:
            result[item_id] = item
    return result


def fetch_network_pools_page(network_id: str, page: int, sort: Optional[str] = None) -> List[Dict[str, Any]]:
    url = f"{GECKO_BASE_URL}/networks/{network_id}/pools"
    params: Dict[str, Any] = {
        "page": page,
        "include": "base_token,quote_token,dex",
    }
    if sort:
        params["sort"] = sort

    data = request_json(url, params=params)
    included_map = build_included_map(data.get("included", []) or [])
    raw_pools = data.get("data", []) or []

    pools: List[Dict[str, Any]] = []

    for pool in raw_pools:
        attrs = pool.get("attributes", {}) or {}
        rel = pool.get("relationships", {}) or {}

        base_id = (((rel.get("base_token") or {}).get("data")) or {}).get("id")
        quote_id = (((rel.get("quote_token") or {}).get("data")) or {}).get("id")
        dex_id = (((rel.get("dex") or {}).get("data")) or {}).get("id")

        base_item = included_map.get(base_id, {})
        quote_item = included_map.get(quote_id, {})
        dex_item = included_map.get(dex_id, {})

        base_attrs = base_item.get("attributes", {}) or {}
        quote_attrs = quote_item.get("attributes", {}) or {}
        dex_attrs = dex_item.get("attributes", {}) or {}

        base_symbol = (base_attrs.get("symbol") or "").upper()
        quote_symbol = (quote_attrs.get("symbol") or "").upper()
        base_name = base_attrs.get("name") or base_symbol or "?"
        quote_name = quote_attrs.get("name") or quote_symbol or "?"
        dex_name = dex_attrs.get("name") or dex_id or "-"

        tx24 = (attrs.get("transactions") or {}).get("h24", {}) or {}
        pool_address = (attrs.get("address") or "").lower()

        pools.append({
            "pool_address": pool_address,
            "label": attrs.get("name") or f"{base_symbol} / {quote_symbol}",
            "base_symbol": base_symbol,
            "quote_symbol": quote_symbol,
            "base_name": base_name,
            "quote_name": quote_name,
            "dex_name": str(dex_name),
            "liquidity_usd": to_float(attrs.get("reserve_in_usd"), 0.0),
            "volume_24h": to_float((attrs.get("volume_usd") or {}).get("h24"), 0.0),
            "fdv_usd": to_float(attrs.get("fdv_usd"), 0.0),
            "market_cap_usd": to_float(attrs.get("market_cap_usd"), 0.0),
            "price_usd": to_float(attrs.get("base_token_price_usd"), 0.0),
            "tx_count_24h": int(to_float(tx24.get("buys"), 0) + to_float(tx24.get("sells"), 0)),
            "url": f"https://www.geckoterminal.com/{network_id}/pools/{pool_address}" if pool_address else "-",
        })

    return pools


def pool_passes_filter(pool: Dict[str, Any]) -> bool:
    if is_bad_name(pool["base_name"]) or is_bad_name(pool["quote_name"]):
        return False

    if is_excluded_pair(pool["base_symbol"], pool["quote_symbol"]):
        return False

    if pool["liquidity_usd"] < 50_000:
        return False

    if pool["volume_24h"] < 20_000:
        return False

    if pool["tx_count_24h"] < 10:
        return False

    return True


def fetch_network_candidates(network_id: str) -> List[Dict[str, Any]]:
    pool_map: Dict[str, Dict[str, Any]] = {}

    # 기본 top pools + 거래량 정렬 페이지를 같이 모아서 후보 확장
    sort_options = [None, "h24_volume_usd_desc"]

    for page in range(1, FETCH_PAGES + 1):
        for sort in sort_options:
            try:
                page_pools = fetch_network_pools_page(network_id, page=page, sort=sort)
            except Exception:
                page_pools = []

            for pool in page_pools:
                if not pool.get("pool_address"):
                    continue
                if not pool_passes_filter(pool):
                    continue

                uid = pool["pool_address"]
                prev = pool_map.get(uid)

                if prev is None:
                    pool_map[uid] = pool
                else:
                    # 더 큰 값 보존
                    prev["liquidity_usd"] = max(prev["liquidity_usd"], pool["liquidity_usd"])
                    prev["volume_24h"] = max(prev["volume_24h"], pool["volume_24h"])
                    prev["tx_count_24h"] = max(prev["tx_count_24h"], pool["tx_count_24h"])

    return list(pool_map.values())


def build_top10(network_id: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    pools = fetch_network_candidates(network_id)

    top_liquidity = sorted(
        pools,
        key=lambda x: (x["liquidity_usd"], x["volume_24h"], x["tx_count_24h"]),
        reverse=True
    )[:10]

    top_volume = sorted(
        pools,
        key=lambda x: (x["volume_24h"], x["liquidity_usd"], x["tx_count_24h"]),
        reverse=True
    )[:10]

    return top_liquidity, top_volume


def format_section(title: str, rows: List[Dict[str, Any]], mode: str) -> str:
    lines = [f"[{title}]"]

    if not rows:
        lines.append("- 후보 없음")
        return "\n".join(lines)

    for i, row in enumerate(rows, start=1):
        if mode == "liquidity":
            lines.append(
                f"{i}) {row['base_symbol']} / {row['quote_symbol']} | {row['dex_name']} | "
                f"유동성 {fmt_num(row['liquidity_usd'])} | 거래량 {fmt_num(row['volume_24h'])}"
            )
        else:
            lines.append(
                f"{i}) {row['base_symbol']} / {row['quote_symbol']} | {row['dex_name']} | "
                f"거래량 {fmt_num(row['volume_24h'])} | 유동성 {fmt_num(row['liquidity_usd'])}"
            )
        lines.append(f"   {row['url']}")

    return "\n".join(lines)


def build_message() -> str:
    sections: List[str] = []

    for network_id, chain_name in NETWORKS.items():
        top_liq, top_vol = build_top10(network_id)

        sections.append(format_section(f"{chain_name} 유동성 TOP 10", top_liq, "liquidity"))
        sections.append("")
        sections.append(format_section(f"{chain_name} 거래량 TOP 10", top_vol, "volume"))
        sections.append("")
        sections.append("")

    return "\n".join(sections).strip()


def main() -> None:
    message = build_message()
    chunks = split_message(message)

    for chunk in chunks:
        send_telegram_message(chunk)


if __name__ == "__main__":
    main()

import os
import requests
from typing import Any, Dict, List, Optional

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
GECKO_API_KEY = os.getenv("GECKO_API_KEY", "").strip()

REQUEST_TIMEOUT = 30
GECKO_BASE_URL = "https://pro-api.coingecko.com/api/v3/onchain"
TOP_N = 5

NETWORKS = {
    "polygon_pos": "Polygon",
    "bsc": "BSC",
}

STABLES = {
    "USDT", "USDC", "USDC.E", "USDT.E", "USDT0", "DAI", "BUSD", "FDUSD",
    "TUSD", "USDP", "USDD", "MAI"
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


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def gecko_headers() -> Dict[str, str]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "pool-top-bot/2.0",
    }
    if GECKO_API_KEY:
        headers["x-cg-pro-api-key"] = GECKO_API_KEY
    return headers


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
        raise ValueError("API 응답 형식 오류")
    return data


def build_included_map(included: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    for item in included or []:
        item_id = item.get("id")
        if item_id:
            result[item_id] = item
    return result


def is_bad_name(text: str) -> bool:
    s = (text or "").lower()
    return any(k in s for k in BAD_KEYWORDS)


def is_excluded_pair(base_symbol: str, quote_symbol: str) -> bool:
    base_symbol = (base_symbol or "").upper()
    quote_symbol = (quote_symbol or "").upper()

    both_stables = base_symbol in STABLES and quote_symbol in STABLES
    both_majors = base_symbol in MAJORS and quote_symbol in MAJORS
    stable_major_mix = (
        (base_symbol in STABLES and quote_symbol in MAJORS)
        or (base_symbol in MAJORS and quote_symbol in STABLES)
    )
    return both_stables or both_majors or stable_major_mix


def pool_passes_filter(pool: Dict[str, Any]) -> bool:
    if is_bad_name(pool["base_name"]) or is_bad_name(pool["quote_name"]):
        return False

    if is_excluded_pair(pool["base_symbol"], pool["quote_symbol"]):
        return False

    if pool["liquidity_usd"] < 50_000:
        return False

    if pool["volume_24h"] < 5_000:
        return False

    return True


def fetch_megafilter_page(network_id: str, sort_value: str, page: int = 1) -> List[Dict[str, Any]]:
    url = f"{GECKO_BASE_URL}/pools/megafilter"
    params = {
        "page": page,
        "networks": network_id,
        "sort": sort_value,
        "include": "base_token,quote_token,dex,network",
        "reserve_in_usd_min": 50000,
        "h24_volume_usd_min": 5000,
    }

    data = request_json(url, params=params)
    included_map = build_included_map(data.get("included", []) or [])
    raw_pools = data.get("data", []) or []

    parsed: List[Dict[str, Any]] = []

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
        dex_name = dex_attrs.get("name") or "-"

        tx24 = (attrs.get("transactions") or {}).get("h24", {}) or {}
        pool_address = (attrs.get("address") or "").lower()

        parsed.append({
            "pool_address": pool_address,
            "base_symbol": base_symbol,
            "quote_symbol": quote_symbol,
            "base_name": base_name,
            "quote_name": quote_name,
            "dex_name": str(dex_name),
            "liquidity_usd": to_float(attrs.get("reserve_in_usd"), 0.0),
            "volume_24h": to_float((attrs.get("volume_usd") or {}).get("h24"), 0.0),
            "tx_count_24h": int(to_float(tx24.get("buys"), 0) + to_float(tx24.get("sells"), 0)),
            "url": f"https://www.geckoterminal.com/{network_id}/pools/{pool_address}" if pool_address else "-",
        })

    return parsed


def build_top5_for_network(network_id: str) -> Dict[str, List[Dict[str, Any]]]:
    pool_map: Dict[str, Dict[str, Any]] = {}

    # 유동성 TOP 5, 거래량 TOP 5 각각 별도 확보
    for sort_value in ["reserve_in_usd_desc", "h24_volume_usd_desc"]:
        rows = fetch_megafilter_page(network_id, sort_value, page=1)

        for row in rows:
            if not row["pool_address"]:
                continue
            if not pool_passes_filter(row):
                continue

            uid = row["pool_address"]
            prev = pool_map.get(uid)
            if prev is None:
                pool_map[uid] = row
            else:
                prev["liquidity_usd"] = max(prev["liquidity_usd"], row["liquidity_usd"])
                prev["volume_24h"] = max(prev["volume_24h"], row["volume_24h"])
                prev["tx_count_24h"] = max(prev["tx_count_24h"], row["tx_count_24h"])

    pools = list(pool_map.values())

    top_liq = sorted(
        pools,
        key=lambda x: (x["liquidity_usd"], x["volume_24h"]),
        reverse=True
    )[:TOP_N]

    top_vol = sorted(
        pools,
        key=lambda x: (x["volume_24h"], x["liquidity_usd"]),
        reverse=True
    )[:TOP_N]

    return {
        "liquidity": top_liq,
        "volume": top_vol,
    }


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
    if not GECKO_API_KEY:
        return (
            "[설정 필요]\n"
            "이 버전은 실제 reserve_in_usd 기준 TOP 5를 위해 CoinGecko/GeckoTerminal Pro의 "
            "megafilter 엔드포인트를 사용합니다.\n"
            "GitHub Secrets에 GECKO_API_KEY 를 추가해 주세요."
        )

    sections: List[str] = []

    for network_id, chain_name in NETWORKS.items():
        result = build_top5_for_network(network_id)

        sections.append(format_section(f"{chain_name} 유동성 TOP 5", result["liquidity"], "liquidity"))
        sections.append("")
        sections.append(format_section(f"{chain_name} 거래량 TOP 5", result["volume"], "volume"))
        sections.append("")
        sections.append("")

    return "\n".join(sections).strip()


def main() -> None:
    message = build_message()
    for chunk in split_message(message):
        send_telegram_message(chunk)


if __name__ == "__main__":
    main()

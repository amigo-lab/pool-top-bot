import os
import requests
from typing import Any, Dict, List, Optional, Set, Tuple

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

REQUEST_TIMEOUT = 30
TOP_N = 5

GECKO_BASE_URL = "https://api.geckoterminal.com/api/v2"
DEX_SEARCH_URL = "https://api.dexscreener.com/latest/dex/search"
DEX_TOKEN_PAIRS_URL = "https://api.dexscreener.com/token-pairs/v1"

NETWORKS = {
    "polygon_pos": {
        "label": "Polygon",
        "dex_chain_id": "polygon",
        "seed_queries": [
            "LGNS",
            "DAI",
            "USDT",
            "USDC",
            "WETH",
            "WBTC",
            "QuickSwap",
            "Uniswap",
            "Aave",
            "Curve",
            "Balancer",
            "Sushi",
            "POL",
            "WPOL",
            "MATIC",
        ],
        # LGNS 같은 주요 후보를 더 잘 잡기 위한 토큰 주소 직접 조회용
        # 필요시 여기 계속 추가 가능
        "seed_token_addresses": [
            # 예: "0x...."
        ],
    },
    "bsc": {
        "label": "BSC",
        "dex_chain_id": "bsc",
        "seed_queries": [
            "WBNB",
            "BNB",
            "BTCB",
            "USDT",
            "USDC",
            "FDUSD",
            "BUSD",
            "CAKE",
            "THENA",
            "PancakeSwap",
            "Venus",
            "Lista",
        ],
        "seed_token_addresses": [
            # 예: "0x...."
        ],
    },
}

STABLES = {
    "USDT", "USDC", "USDC.E", "USDT.E", "USDT0", "DAI", "BUSD", "FDUSD",
    "TUSD", "USDP", "USDD", "MAI",
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

REQUEST_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "pool-top-bot/3.0",
}


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


def request_json(url: str, params: Optional[Dict[str, Any]] = None) -> Any:
    r = requests.get(url, params=params, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()


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


def normalize_pool_row(row: Dict[str, Any]) -> Dict[str, Any]:
    row["base_symbol"] = (row.get("base_symbol") or "").upper()
    row["quote_symbol"] = (row.get("quote_symbol") or "").upper()
    row["base_name"] = row.get("base_name") or row["base_symbol"] or "?"
    row["quote_name"] = row.get("quote_name") or row["quote_symbol"] or "?"
    row["dex_name"] = row.get("dex_name") or "-"
    row["liquidity_usd"] = to_float(row.get("liquidity_usd"), 0.0)
    row["volume_24h"] = to_float(row.get("volume_24h"), 0.0)
    row["tx_count_24h"] = int(to_float(row.get("tx_count_24h"), 0))
    row["url"] = row.get("url") or "-"
    row["pool_address"] = (row.get("pool_address") or "").lower()
    return row


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


def pool_uid(chain_key: str, pool_address: str, url: str, base_symbol: str, quote_symbol: str, dex_name: str) -> str:
    if pool_address:
        return f"{chain_key}:{pool_address}"
    if url and url != "-":
        return f"{chain_key}:{url}"
    return f"{chain_key}:{base_symbol}:{quote_symbol}:{dex_name}"


def merge_pool(pool_map: Dict[str, Dict[str, Any]], chain_key: str, row: Dict[str, Any]) -> None:
    row = normalize_pool_row(row)

    if not pool_passes_filter(row):
        return

    uid = pool_uid(
        chain_key,
        row["pool_address"],
        row["url"],
        row["base_symbol"],
        row["quote_symbol"],
        row["dex_name"],
    )

    prev = pool_map.get(uid)
    if prev is None:
        pool_map[uid] = row
        return

    prev["liquidity_usd"] = max(prev["liquidity_usd"], row["liquidity_usd"])
    prev["volume_24h"] = max(prev["volume_24h"], row["volume_24h"])
    prev["tx_count_24h"] = max(prev["tx_count_24h"], row["tx_count_24h"])

    if prev.get("url") == "-" and row.get("url") != "-":
        prev["url"] = row["url"]


# ----------------------------
# GeckoTerminal free top-pools
# ----------------------------
def gecko_build_included_map(included: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    result = {}
    for item in included or []:
        item_id = item.get("id")
        if item_id:
            result[item_id] = item
    return result


def fetch_gecko_top_pools_page(network_id: str, page: int = 1, sort: Optional[str] = None) -> List[Dict[str, Any]]:
    url = f"{GECKO_BASE_URL}/networks/{network_id}/pools"
    params: Dict[str, Any] = {
        "page": page,
        "include": "base_token,quote_token,dex",
    }
    if sort:
        params["sort"] = sort

    data = request_json(url, params=params)
    if not isinstance(data, dict):
        return []

    included_map = gecko_build_included_map(data.get("included", []) or [])
    raw_pools = data.get("data", []) or []
    rows: List[Dict[str, Any]] = []

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

        tx24 = (attrs.get("transactions") or {}).get("h24", {}) or {}
        address = (attrs.get("address") or "").lower()

        rows.append({
            "pool_address": address,
            "base_symbol": base_attrs.get("symbol") or "",
            "quote_symbol": quote_attrs.get("symbol") or "",
            "base_name": base_attrs.get("name") or "",
            "quote_name": quote_attrs.get("name") or "",
            "dex_name": dex_attrs.get("name") or dex_id or "-",
            "liquidity_usd": attrs.get("reserve_in_usd"),
            "volume_24h": (attrs.get("volume_usd") or {}).get("h24"),
            "tx_count_24h": to_float(tx24.get("buys"), 0) + to_float(tx24.get("sells"), 0),
            "url": f"https://www.geckoterminal.com/{network_id}/pools/{address}" if address else "-",
        })

    return rows


def collect_from_gecko(chain_key: str, pool_map: Dict[str, Dict[str, Any]]) -> None:
    for page in range(1, 6):
        for sort in [None, "h24_volume_usd_desc"]:
            try:
                rows = fetch_gecko_top_pools_page(chain_key, page=page, sort=sort)
            except Exception:
                rows = []

            for row in rows:
                merge_pool(pool_map, chain_key, row)


# ----------------------------
# DexScreener free search/token-pairs
# ----------------------------
def fetch_dex_search(query: str) -> List[Dict[str, Any]]:
    data = request_json(DEX_SEARCH_URL, params={"q": query})
    if not isinstance(data, dict):
        return []
    return data.get("pairs", []) or []


def fetch_dex_token_pairs(chain_id: str, token_address: str) -> List[Dict[str, Any]]:
    url = f"{DEX_TOKEN_PAIRS_URL}/{chain_id}/{token_address}"
    data = request_json(url)
    if isinstance(data, list):
        return data
    return []


def dex_pair_to_row(pair: Dict[str, Any]) -> Dict[str, Any]:
    base = pair.get("baseToken") or {}
    quote = pair.get("quoteToken") or {}
    tx24 = (pair.get("txns") or {}).get("h24", {}) or {}

    return {
        "pool_address": (pair.get("pairAddress") or "").lower(),
        "base_symbol": base.get("symbol") or "",
        "quote_symbol": quote.get("symbol") or "",
        "base_name": base.get("name") or "",
        "quote_name": quote.get("name") or "",
        "dex_name": pair.get("dexId") or "-",
        "liquidity_usd": (pair.get("liquidity") or {}).get("usd"),
        "volume_24h": (pair.get("volume") or {}).get("h24"),
        "tx_count_24h": to_float(tx24.get("buys"), 0) + to_float(tx24.get("sells"), 0),
        "url": pair.get("url") or "-",
    }


def collect_from_dex_search(chain_key: str, dex_chain_id: str, seed_queries: List[str], pool_map: Dict[str, Dict[str, Any]]) -> None:
    for query in seed_queries:
        try:
            pairs = fetch_dex_search(query)
        except Exception:
            pairs = []

        for pair in pairs:
            if (pair.get("chainId") or "").lower() != dex_chain_id.lower():
                continue
            merge_pool(pool_map, chain_key, dex_pair_to_row(pair))


def collect_from_dex_token_pairs(chain_key: str, dex_chain_id: str, token_addresses: List[str], pool_map: Dict[str, Dict[str, Any]]) -> None:
    for token_address in token_addresses:
        try:
            pairs = fetch_dex_token_pairs(dex_chain_id, token_address)
        except Exception:
            pairs = []

        for pair in pairs:
            if (pair.get("chainId") or "").lower() != dex_chain_id.lower():
                continue
            merge_pool(pool_map, chain_key, dex_pair_to_row(pair))


def build_top5_for_network(chain_key: str, chain_cfg: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    pool_map: Dict[str, Dict[str, Any]] = {}

    collect_from_gecko(chain_key, pool_map)
    collect_from_dex_search(chain_key, chain_cfg["dex_chain_id"], chain_cfg["seed_queries"], pool_map)
    collect_from_dex_token_pairs(chain_key, chain_cfg["dex_chain_id"], chain_cfg["seed_token_addresses"], pool_map)

    pools = list(pool_map.values())

    top_liq = sorted(
        pools,
        key=lambda x: (x["liquidity_usd"], x["volume_24h"], x["tx_count_24h"]),
        reverse=True
    )[:TOP_N]

    top_vol = sorted(
        pools,
        key=lambda x: (x["volume_24h"], x["liquidity_usd"], x["tx_count_24h"]),
        reverse=True
    )[:TOP_N]

    return {"liquidity": top_liq, "volume": top_vol}


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

    for chain_key, chain_cfg in NETWORKS.items():
        result = build_top5_for_network(chain_key, chain_cfg)

        sections.append(format_section(f"{chain_cfg['label']} 유동성 TOP 5", result["liquidity"], "liquidity"))
        sections.append("")
        sections.append(format_section(f"{chain_cfg['label']} 거래량 TOP 5", result["volume"], "volume"))
        sections.append("")
        sections.append("")

    sections.append("[안내]")
    sections.append("- 무료 API 조합 버전입니다.")
    sections.append("- Gecko 상위 풀 페이지 + DexScreener 검색/토큰풀 조회를 합쳐 재정렬합니다.")
    sections.append("- 절대적인 체인 전체 순위는 아니지만, 무료 범위에서는 누락을 줄인 방식입니다.")

    return "\n".join(sections).strip()


def main() -> None:
    message = build_message()
    for chunk in split_message(message):
        send_telegram_message(chunk)


if __name__ == "__main__":
    main()

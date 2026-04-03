import os
import json
import requests
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

TOP_N = 5
REQUEST_TIMEOUT = 30
STATE_FILE = "state.json"

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
        "keywords": [
            "LGNS", "Longinus", "DAI", "USDT", "USDC", "QuickSwap", "Uniswap",
            "Aave", "Curve", "Balancer", "WETH", "WBTC", "POL", "WPOL", "MATIC"
        ],
    },
    "bsc": {
        "label": "BSC",
        "dex_chain": "bsc",
        "keywords": [
            "CAKE", "WBNB", "BNB", "BTCB", "USDT", "USDC", "PancakeSwap", "THENA"
        ],
    },
}

# 공통 기준
MIN_LIQUIDITY_DEFAULT = 50_000
MIN_VOLUME_DEFAULT = 5_000

# BSC 강화 기준
MIN_LIQUIDITY_BSC = 500_000
MIN_VOLUME_BSC = 50_000
MIN_LIQUIDITY_FOR_BSC_VOLUME_RANK = 1_000_000

BSC_ALLOWED_DEX_KEYWORDS = {
    "pancakeswap",
    "thena",
    "biswap",
}

# 급증 알림 기준
SURGE_MIN_PREV_LIQ = 100_000
SURGE_MIN_ABS_DELTA = 200_000
SURGE_MULTIPLIER = 2.0

# 신규 풀 알림 기준
NEW_MIN_LIQ = 200_000
NEW_MIN_VOL = 50_000
NEW_MAX_AGE_HOURS = 24


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


def now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def ts_to_text(ts: Optional[int]) -> str:
    if not ts:
        return "-"
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def hours_since(ts: Optional[int]) -> Optional[float]:
    if not ts:
        return None
    return (now_ts() - int(ts)) / 3600.0


def load_state() -> Dict[str, Any]:
    if not os.path.exists(STATE_FILE):
        return {"pools": {}}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"pools": {}}
        if "pools" not in data or not isinstance(data["pools"], dict):
            data["pools"] = {}
        return data
    except Exception:
        return {"pools": {}}


def save_state(state: Dict[str, Any]) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def request_json(url: str, params: Optional[Dict[str, Any]] = None) -> Any:
    r = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()


def normalize_symbol(sym: str) -> str:
    s = (sym or "").upper()
    return STABLE_ALIASES.get(s, s)


def is_bad_token(symbol: str) -> bool:
    s = (symbol or "").lower()
    return any(k in s for k in BAD_KEYWORDS)


def valid_pair(base: str, quote: str) -> bool:
    base = normalize_symbol(base)
    quote = normalize_symbol(quote)

    if not base or not quote:
        return False

    if base in STABLES and quote in STABLES:
        return False

    if base in MAJORS and quote in MAJORS:
        return False

    if (base in STABLES and quote in MAJORS) or (base in MAJORS and quote in STABLES):
        return False

    if is_bad_token(base) or is_bad_token(quote):
        return False

    return True


def extract_pool_address_from_url(url: str) -> str:
    if not url:
        return ""
    try:
        return url.rstrip("/").split("/")[-1].lower()
    except Exception:
        return ""


def normalize_pool(row: Dict[str, Any]) -> Dict[str, Any]:
    row["pair"] = row.get("pair", "-")
    row["base_symbol"] = normalize_symbol(row.get("base_symbol") or "")
    row["quote_symbol"] = normalize_symbol(row.get("quote_symbol") or "")
    row["dex"] = row.get("dex") or "-"
    row["liq"] = to_float(row.get("liq"), 0.0)
    row["vol"] = to_float(row.get("vol"), 0.0)
    row["url"] = row.get("url") or "-"
    row["pool_address"] = (row.get("pool_address") or "").lower()
    row["pair_created_at"] = int(to_float(row.get("pair_created_at"), 0))
    row["chain"] = row.get("chain") or "-"
    row["pair"] = f"{row['base_symbol']}/{row['quote_symbol']}" if row["base_symbol"] and row["quote_symbol"] else row["pair"]
    return row


def unique_key(pool: Dict[str, Any]) -> str:
    if pool.get("pool_address"):
        return f"{pool.get('chain','-')}:{pool['pool_address']}"
    extracted = extract_pool_address_from_url(pool.get("url", ""))
    if extracted:
        return f"{pool.get('chain','-')}:{extracted}"
    return f"{pool.get('chain','-')}:{pool.get('pair','')}_{pool.get('dex','')}".lower()


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

        if (not old.get("pair_created_at")) and p.get("pair_created_at"):
            old["pair_created_at"] = p["pair_created_at"]

    return list(uniq.values())


def deduplicate_same_pair(chain: str, pools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    base_token_count: Dict[str, int] = {}

    for p in sorted(pools, key=lambda x: (x["liq"], x["vol"]), reverse=True):
        base = normalize_symbol(p.get("base_symbol", ""))
        quote = normalize_symbol(p.get("quote_symbol", ""))
        pair_key = f"{base}/{quote}"

        if pair_key in result:
            continue

        # base 토큰 반복 제한
        if chain == "bsc":
            max_per_base = 1
        else:
            max_per_base = 2

        if base != "LGNS":
            cnt = base_token_count.get(base, 0)
            if cnt >= max_per_base:
                continue
            base_token_count[base] = cnt + 1

        result[pair_key] = p

    return list(result.values())


def is_allowed_bsc_dex(dex_name: str) -> bool:
    d = (dex_name or "").lower()
    return any(k in d for k in BSC_ALLOWED_DEX_KEYWORDS)


def final_filter(chain: str, pools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    filtered: List[Dict[str, Any]] = []

    for p in pools:
        base = normalize_symbol(p["base_symbol"])
        quote = normalize_symbol(p["quote_symbol"])

        if is_bad_token(base) or is_bad_token(quote):
            continue

        if p["vol"] > p["liq"] * 3:
            continue

        if chain == "bsc":
            if p["liq"] < MIN_LIQUIDITY_BSC:
                continue
            if p["vol"] < MIN_VOLUME_BSC:
                continue
            if not is_allowed_bsc_dex(p["dex"]):
                continue

        filtered.append(p)

    return filtered


def pool_passes_common_filters(base_s: str, quote_s: str, liquidity: float, volume_h24: float) -> bool:
    if not valid_pair(base_s, quote_s):
        return False

    if liquidity < MIN_LIQUIDITY_DEFAULT:
        return False

    if volume_h24 < MIN_VOLUME_DEFAULT:
        return False

    if volume_h24 > liquidity * 3:
        return False

    return True


def fetch_gecko(chain: str) -> List[Dict[str, Any]]:
    pools: List[Dict[str, Any]] = []

    for page in range(1, 6):
        try:
            data = request_json(
                GECKO_URL.format(chain=chain),
                params={"page": page, "include": "base_token,quote_token,dex"},
            )
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

                base_s = normalize_symbol(base.get("symbol") or "")
                quote_s = normalize_symbol(quote.get("symbol") or "")

                liquidity = to_float(attr.get("reserve_in_usd"), 0.0)
                volume_h24 = to_float((attr.get("volume_usd") or {}).get("h24"), 0.0)

                if not pool_passes_common_filters(base_s, quote_s, liquidity, volume_h24):
                    continue

                address = (attr.get("address") or "").lower()

                pools.append({
                    "chain": chain,
                    "pair": f"{base_s}/{quote_s}",
                    "base_symbol": base_s,
                    "quote_symbol": quote_s,
                    "dex": dex.get("name", "-"),
                    "liq": liquidity,
                    "vol": volume_h24,
                    "pool_address": address,
                    "url": f"https://www.geckoterminal.com/{chain}/pools/{address}" if address else "-",
                    "pair_created_at": 0,
                })
            except Exception:
                continue

    return pools


def fetch_dex(chain: str, keywords: List[str]) -> List[Dict[str, Any]]:
    pools: List[Dict[str, Any]] = []

    for keyword in keywords:
        try:
            data = request_json(DEX_SEARCH_URL, params={"q": keyword})
        except Exception:
            continue

        for p in data.get("pairs", []):
            try:
                if (p.get("chainId") or "").lower() != chain.lower():
                    continue

                base = p.get("baseToken", {}) or {}
                quote = p.get("quoteToken", {}) or {}

                base_s = normalize_symbol(base.get("symbol") or "")
                quote_s = normalize_symbol(quote.get("symbol") or "")

                liquidity = to_float((p.get("liquidity") or {}).get("usd"), 0.0)
                volume_h24 = to_float((p.get("volume") or {}).get("h24"), 0.0)

                if not pool_passes_common_filters(base_s, quote_s, liquidity, volume_h24):
                    continue

                pools.append({
                    "chain": chain,
                    "pair": f"{base_s}/{quote_s}",
                    "base_symbol": base_s,
                    "quote_symbol": quote_s,
                    "dex": p.get("dexId", "-"),
                    "liq": liquidity,
                    "vol": volume_h24,
                    "pool_address": (p.get("pairAddress") or "").lower(),
                    "url": p.get("url") or "-",
                    "pair_created_at": int(to_float(p.get("pairCreatedAt"), 0) / 1000),
                })
            except Exception:
                continue

    return pools


def inject_lgns_manual() -> List[Dict[str, Any]]:
    return [{
        "chain": "polygon",
        "pair": "LGNS/DAI",
        "base_symbol": "LGNS",
        "quote_symbol": "DAI",
        "dex": "QuickSwap",
        "liq": 480_000_000,
        "vol": 40_000_000,
        "pool_address": "0x882df4b0fb50a229c3b4124eb18c759911485bfb",
        "url": "https://dexscreener.com/polygon/0x882df4b0fb50a229c3b4124eb18c759911485bfb",
        "pair_created_at": 0,
    }]


def build_pool_universe(chain: str, dex_chain: str, keywords: List[str]) -> List[Dict[str, Any]]:
    gecko_pools = fetch_gecko(chain)
    dex_pools = fetch_dex(dex_chain, keywords)

    all_pools = gecko_pools + dex_pools

    if chain == "polygon_pos":
        all_pools += inject_lgns_manual()

    pools = merge_pools(all_pools)
    pools = deduplicate_same_pair(dex_chain, pools)
    pools = final_filter(chain=dex_chain, pools=pools)

    return pools


def detect_liquidity_surges(chain_label: str, pools: List[Dict[str, Any]], state: Dict[str, Any]) -> List[str]:
    alerts: List[str] = []
    pool_state = state.setdefault("pools", {})

    for p in pools:
        key = unique_key(p)
        prev = pool_state.get(key, {})
        prev_liq = to_float(prev.get("liq"), 0.0)
        curr_liq = p["liq"]
        delta = curr_liq - prev_liq

        if (
            prev_liq >= SURGE_MIN_PREV_LIQ
            and curr_liq >= prev_liq * SURGE_MULTIPLIER
            and delta >= SURGE_MIN_ABS_DELTA
        ):
            alerts.append(
                f"🚀 [{chain_label} 유동성 급증]\n"
                f"{p['pair']} | {p['dex']}\n"
                f"이전: {fmt_num(prev_liq)} → 현재: {fmt_num(curr_liq)}\n"
                f"증가액: {fmt_num(delta)}\n"
                f"{p['url']}"
            )

    return alerts


def detect_new_pools(chain_label: str, pools: List[Dict[str, Any]], state: Dict[str, Any]) -> List[str]:
    alerts: List[str] = []
    pool_state = state.setdefault("pools", {})

    for p in pools:
        key = unique_key(p)
        prev = pool_state.get(key)

        if prev is None:
            created_at = p.get("pair_created_at", 0)
            age_h = hours_since(created_at)

            if (
                created_at
                and age_h is not None
                and age_h <= NEW_MAX_AGE_HOURS
                and p["liq"] >= NEW_MIN_LIQ
                and p["vol"] >= NEW_MIN_VOL
            ):
                alerts.append(
                    f"🆕 [{chain_label} 신규 풀 감지]\n"
                    f"{p['pair']} | {p['dex']}\n"
                    f"유동성: {fmt_num(p['liq'])}\n"
                    f"거래량: {fmt_num(p['vol'])}\n"
                    f"생성시각: {ts_to_text(created_at)}\n"
                    f"{p['url']}"
                )

    return alerts


def update_state_with_pools(pools: List[Dict[str, Any]], state: Dict[str, Any]) -> None:
    pool_state = state.setdefault("pools", {})
    now = now_ts()

    for p in pools:
        key = unique_key(p)
        old = pool_state.get(key, {})

        first_seen = old.get("first_seen", now)
        created_at = p.get("pair_created_at", 0) or old.get("pair_created_at", 0)

        pool_state[key] = {
            "pair": p["pair"],
            "dex": p["dex"],
            "liq": p["liq"],
            "vol": p["vol"],
            "url": p["url"],
            "chain": p["chain"],
            "first_seen": first_seen,
            "last_seen": now,
            "pair_created_at": created_at,
        }


def build_top_sections(name: str, pools: List[Dict[str, Any]]) -> str:
    top_liq = sorted(pools, key=lambda x: (x["liq"], x["vol"]), reverse=True)[:TOP_N]
    top_vol = sorted(
        [p for p in pools if p["liq"] >= (MIN_LIQUIDITY_FOR_BSC_VOLUME_RANK if name == "BSC" else MIN_LIQUIDITY_DEFAULT)],
        key=lambda x: (x["vol"], x["liq"]),
        reverse=True
    )[:TOP_N]

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
    state = load_state()
    sections: List[str] = []
    alerts: List[str] = []
    all_current_pools: List[Dict[str, Any]] = []

    for chain, cfg in NETWORKS.items():
        pools = build_pool_universe(chain=chain, dex_chain=cfg["dex_chain"], keywords=cfg["keywords"])
        all_current_pools.extend(pools)

        sections.append(build_top_sections(cfg["label"], pools))
        alerts.extend(detect_liquidity_surges(cfg["label"], pools, state))
        alerts.extend(detect_new_pools(cfg["label"], pools, state))

    update_state_with_pools(all_current_pools, state)
    save_state(state)

    message_parts: List[str] = []

    if alerts:
        message_parts.append("[알림]")
        message_parts.extend(alerts)
        message_parts.append("")

    message_parts.extend(sections)
    message_parts.append("")
    message_parts.append("[안내]")
    message_parts.append("- Gecko + DexScreener 무료 조합")
    message_parts.append("- LGNS 대표 풀 강제 포함")
    message_parts.append("- pool_address 기준 중복 제거")
    message_parts.append("- 같은 pair는 가장 큰 유동성 1개만 유지")
    message_parts.append("- USDT0/USDC.E 등 표기 통합")
    message_parts.append("- 밈코인/펌핑 필터 적용")
    message_parts.append("- BSC는 보수적 DEX/유동성 필터 적용")
    message_parts.append("- 유동성 급증 알림 포함")
    message_parts.append("- 신규 풀 탐지 포함")

    final_message = "\n\n".join(message_parts)

    for chunk in split_message(final_message):
        send_telegram_message(chunk)


if __name__ == "__main__":
    main()

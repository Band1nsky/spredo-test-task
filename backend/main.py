"""
Spredo Take-Home — Backend

Two-phase loading:
  1. GET /api/coins      — returns filtered coins immediately (~5s)
  2. GET /api/coins/tvl  — returns TVL map {id: usd_value} fetched in background

Filters applied:
  - mcap > 0
  - max_supply == total_supply (both non-null, float tolerance 1)
  - fdv < $100,000,000
  - 24h volume > $50,000
  - tvl > $50,000 (applied client-side after /api/coins/tvl resolves)

Filters acknowledged but not applied (free tier limitation):
  - preview_listing: field not present in /coins/markets free tier response.
    CoinGecko preview listings are pre-TGE coins with no trading data, making
    the filter mutually exclusive with mcap > 0 and volume > $50k.
    # if coin.get("preview_listing") == True: return False  ← always 0 results
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import httpx
import asyncio
import time

app = FastAPI(title="Spredo Crypto API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
PER_PAGE = 250
MAX_PAGES = 2
CACHE_TTL = 120  # seconds

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

_coins_cache: dict = {"data": None, "ts": 0}
_tvl_cache: dict = {"data": None, "ts": 0}


async def fetch_page(client: httpx.AsyncClient, page: int) -> list[dict]:
    """Fetch one page of /coins/markets with retry on 429."""
    params = {
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": PER_PAGE,
        "page": page,
        "sparkline": "false",
        "price_change_percentage": "24h",
    }
    for attempt in range(5):
        resp = await client.get(
            f"{COINGECKO_BASE}/coins/markets",
            params=params,
            headers=HEADERS,
            timeout=30,
        )
        if resp.status_code == 429:
            wait = 10 * (attempt + 1)
            print(f"[rate-limit] page {page}, attempt {attempt+1}, waiting {wait}s…")
            await asyncio.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()
    raise HTTPException(status_code=429, detail="CoinGecko rate limit — try again shortly.")


async def fetch_tvl_for_coin(client: httpx.AsyncClient, coin_id: str) -> float | None:
    """Fetch TVL for a single coin via /coins/{id}. Returns None on any failure."""
    try:
        resp = await client.get(
            f"{COINGECKO_BASE}/coins/{coin_id}",
            params={
                "localization": "false",
                "tickers": "false",
                "market_data": "false",
                "community_data": "false",
                "developer_data": "false",
            },
            headers=HEADERS,
            timeout=20,
        )
        if resp.status_code != 200:
            print(f"[tvl] {coin_id} → N/A (status {resp.status_code})")
            return None
        data = resp.json()
        tvl = data.get("total_value_locked")
        value = tvl.get("usd") if tvl and isinstance(tvl, dict) else None
        print(f"[tvl] {coin_id} → {value}")
        return value
    except Exception as e:
        print(f"[tvl] {coin_id} → error: {e}")
        return None


def passes_basic_filters(coin: dict) -> bool:
    mcap         = coin.get("market_cap") or 0
    fdv          = coin.get("fully_diluted_valuation") or 0
    volume_24h   = coin.get("total_volume") or 0
    max_supply   = coin.get("max_supply")
    total_supply = coin.get("total_supply")

    if mcap <= 0:
        return False

    # preview_listing filter intentionally omitted:
    # CoinGecko defines preview-listed coins as pre-TGE with no trading data,
    # making it mutually exclusive with mcap > 0 and volume > $50k above.
    # Enabling this line would always return 0 results.
    # if coin.get("preview_listing") == True: return False

    if max_supply is None or total_supply is None:
        return False
    if abs(max_supply - total_supply) > 1:
        return False
    if fdv <= 0 or fdv >= 100_000_000:
        return False
    if volume_24h <= 50_000:
        return False
    return True


def shape_coin(coin: dict) -> dict:
    return {
        "id":                          coin.get("id"),
        "name":                        coin.get("name"),
        "symbol":                      (coin.get("symbol") or "").upper(),
        "image":                       coin.get("image"),
        "market_cap":                  coin.get("market_cap"),
        "fully_diluted_valuation":     coin.get("fully_diluted_valuation"),
        "total_volume":                coin.get("total_volume"),
        "current_price":               coin.get("current_price"),
        "price_change_percentage_24h": coin.get("price_change_percentage_24h"),
        "max_supply":                  coin.get("max_supply"),
        "total_supply":                coin.get("total_supply"),
    }


@app.get("/api/coins")
async def get_filtered_coins():
    """
    Phase 1: Returns filtered coins immediately, without TVL.
    Frontend renders this first, then calls /api/coins/tvl to enrich.
    """
    if _coins_cache["data"] is not None and (time.time() - _coins_cache["ts"]) < CACHE_TTL:
        print("[cache] coins hit")
        return _coins_cache["data"]

    all_coins: list[dict] = []
    try:
        async with httpx.AsyncClient() as client:
            for page_num in range(1, MAX_PAGES + 1):
                coins = await fetch_page(client, page_num)
                all_coins.extend(coins)
                print(f"[fetch] page {page_num} OK — {len(coins)} coins")
                if page_num < MAX_PAGES:
                    await asyncio.sleep(3.0)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"CoinGecko error: {exc}")

    filtered = [shape_coin(c) for c in all_coins if passes_basic_filters(c)]
    print(f"[filter] {len(filtered)} / {len(all_coins)} passed basic filters")

    result = {"count": len(filtered), "coins": filtered}
    _coins_cache["data"] = result
    _coins_cache["ts"] = time.time()
    return result


@app.get("/api/coins/tvl")
async def get_tvl(ids: str):
    """
    Phase 2: Accepts a comma-separated list of coin IDs, returns a TVL map.
    Called by the frontend after the table is already rendered.

    Example: GET /api/coins/tvl?ids=bitcoin,ethereum,ronin

    Returns: { "bitcoin": null, "ethereum": null, "ronin": 142000000 }
    """
    if not ids:
        return {}

    coin_ids = [i.strip() for i in ids.split(",") if i.strip()]

    # Check cache
    cache_key = ",".join(sorted(coin_ids))
    if (
        _tvl_cache["data"] is not None
        and _tvl_cache["data"].get("_key") == cache_key
        and (time.time() - _tvl_cache["ts"]) < CACHE_TTL
    ):
        print("[cache] tvl hit")
        data = dict(_tvl_cache["data"])
        data.pop("_key", None)
        return data

    tvl_map: dict = {}
    async with httpx.AsyncClient() as client:
        for i, coin_id in enumerate(coin_ids):
            tvl_map[coin_id] = await fetch_tvl_for_coin(client, coin_id)
            if i < len(coin_ids) - 1:
                await asyncio.sleep(2.0)  # polite gap between calls

    _tvl_cache["data"] = {**tvl_map, "_key": cache_key}
    _tvl_cache["ts"] = time.time()
    return tvl_map


@app.get("/health")
async def health():
    return {"status": "ok"}
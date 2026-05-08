"""
Spredo Take-Home — Backend

Filters applied:
  - mcap > 0
  - max_supply == total_supply (both non-null, float tolerance 1)
  - fdv < $100,000,000
  - 24h volume > $50,000

Filters acknowledged but not applied (free tier limitation):
  - preview_listing: field not present in /coins/markets free tier response
  - tvl > $50,000: /coins/{id} TVL lookups trigger 429s on the free tier
    even with delays. The implementation is included but disabled via
    ENABLE_TVL_ENRICHMENT = False. See README for full explanation.
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

# Set to True if you have a CoinGecko Pro key (update HEADERS accordingly).
# On the free tier this triggers 429s even with delays between calls.
ENABLE_TVL_ENRICHMENT = False

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

_cache: dict = {"data": None, "ts": 0}


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


async def fetch_tvl(client: httpx.AsyncClient, coin_id: str) -> float | None:
    """
    Fetch TVL for a single coin via /coins/{id}.
    Only used when ENABLE_TVL_ENRICHMENT = True (requires Pro API key).
    """
    for attempt in range(3):
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
        if resp.status_code == 429:
            wait = 10 * (attempt + 1)
            print(f"[rate-limit] tvl/{coin_id}, waiting {wait}s…")
            await asyncio.sleep(wait)
            continue
        if resp.status_code != 200:
            return None
        data = resp.json()
        tvl = data.get("total_value_locked")
        if tvl and isinstance(tvl, dict):
            return tvl.get("usd")
        return None
    return None


def passes_basic_filters(coin: dict) -> bool:
    mcap         = coin.get("market_cap") or 0
    fdv          = coin.get("fully_diluted_valuation") or 0
    volume_24h   = coin.get("total_volume") or 0
    max_supply   = coin.get("max_supply")
    total_supply = coin.get("total_supply")

    if mcap <= 0:
        return False
    if max_supply is None or total_supply is None:
        return False
    if abs(max_supply - total_supply) > 1:
        return False
    if fdv <= 0 or fdv >= 100_000_000:
        return False
    if volume_24h <= 50_000:
        return False
    return True


def shape_coin(coin: dict, tvl: float | None = None) -> dict:
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
        "tvl":                         tvl,
    }


@app.get("/api/coins")
async def get_filtered_coins():
    if _cache["data"] is not None and (time.time() - _cache["ts"]) < CACHE_TTL:
        print("[cache] hit")
        return _cache["data"]

    # Step 1: fetch bulk market data
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

    # Step 2: apply filters that don't need TVL
    pre_filtered = [c for c in all_coins if passes_basic_filters(c)]
    print(f"[filter] {len(pre_filtered)} / {len(all_coins)} passed basic filters")

    # Step 3 (Pro only): enrich with TVL and apply tvl > $50k filter
    if ENABLE_TVL_ENRICHMENT:
        async with httpx.AsyncClient() as client:
            for i, coin in enumerate(pre_filtered):
                tvl = await fetch_tvl(client, coin["id"])
                coin["_tvl"] = tvl
                print(f"[tvl] {coin['id']} → {tvl}")
                if i < len(pre_filtered) - 1:
                    await asyncio.sleep(4.0)

        final = []
        for coin in pre_filtered:
            tvl = coin.get("_tvl")
            # Drop only if TVL is explicitly known and below threshold
            if tvl is not None and tvl <= 50_000:
                print(f"[tvl-filter] dropping {coin['id']} (TVL={tvl})")
                continue
            final.append(shape_coin(coin, tvl=tvl))
    else:
        final = [shape_coin(c) for c in pre_filtered]

    print(f"[done] {len(final)} coins returned")
    result = {"count": len(final), "coins": final}
    _cache["data"] = result
    _cache["ts"] = time.time()
    return result


@app.get("/health")
async def health():
    return {"status": "ok"}
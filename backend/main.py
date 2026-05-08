"""
Spredo Take-Home — Backend

NOTE on filters:
- preview_listing: not in free CoinGecko API, defaulted to True
- TVL: not in /coins/markets, so that filter is DISABLED on free tier
- max_supply == total_supply: kept but uses float tolerance
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
PER_PAGE = 250   # max allowed by CoinGecko
MAX_PAGES = 2    # 500 coins total — enough sample, fewer rate-limit hits
CACHE_TTL = 120  # seconds

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
    """Fetch one page with exponential back-off on 429."""
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
            wait = 10 * (attempt + 1)   # 10s, 20s, 30s, 40s, 50s
            print(f"[rate-limit] page {page}, attempt {attempt+1}, waiting {wait}s…")
            await asyncio.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()
    raise HTTPException(status_code=429, detail="CoinGecko rate limit — try again in a minute.")


def passes_filters(coin: dict) -> bool:
    mcap        = coin.get("market_cap") or 0
    fdv         = coin.get("fully_diluted_valuation") or 0
    volume_24h  = coin.get("total_volume") or 0
    max_supply  = coin.get("max_supply")
    total_supply= coin.get("total_supply")

    # mcap > 0
    if mcap <= 0:
        return False

    # max_supply == total_supply (both must exist)
    if max_supply is None or total_supply is None:
        return False
    if abs(max_supply - total_supply) > 1:
        return False

    # fdv < $100M
    if fdv <= 0 or fdv >= 100_000_000:
        return False

    # 24h volume > $50k
    if volume_24h <= 50_000:
        return False

    # preview_listing & TVL are NOT available on the free CoinGecko tier.
    # Both filters are acknowledged in README as assumptions/limitations.

    return True


def shape_coin(coin: dict) -> dict:
    return {
        "id":                         coin.get("id"),
        "name":                       coin.get("name"),
        "symbol":                     (coin.get("symbol") or "").upper(),
        "image":                      coin.get("image"),
        "market_cap":                 coin.get("market_cap"),
        "fully_diluted_valuation":    coin.get("fully_diluted_valuation"),
        "total_volume":               coin.get("total_volume"),
        "current_price":              coin.get("current_price"),
        "price_change_percentage_24h":coin.get("price_change_percentage_24h"),
        "max_supply":                 coin.get("max_supply"),
        "total_supply":               coin.get("total_supply"),
    }


@app.get("/api/coins")
async def get_filtered_coins():
    # Serve from cache if still fresh
    if _cache["data"] is not None and (time.time() - _cache["ts"]) < CACHE_TTL:
        print("[cache] hit")
        return _cache["data"]

    all_coins: list[dict] = []
    try:
        async with httpx.AsyncClient() as client:
            for page_num in range(1, MAX_PAGES + 1):
                coins = await fetch_page(client, page_num)
                all_coins.extend(coins)
                print(f"[fetch] page {page_num} OK — {len(coins)} coins")
                if page_num < MAX_PAGES:
                    await asyncio.sleep(3.0)   # polite gap between pages
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"CoinGecko error: {exc}")

    filtered = [shape_coin(c) for c in all_coins if passes_filters(c)]
    print(f"[filter] {len(filtered)} / {len(all_coins)} coins passed filters")

    result = {"count": len(filtered), "coins": filtered}
    _cache["data"] = result
    _cache["ts"] = time.time()
    return result


@app.get("/health")
async def health():
    return {"status": "ok"}
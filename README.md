# Spredo Take-Home — Full Stack Crypto Dashboard

## What Was Built

| | |
|---|---|
| **Backend** | FastAPI (Python) — fetches CoinGecko `/coins/markets`, applies filters, exposes `GET /api/coins` |
| **Frontend** | React + Vite — displays filtered coins with search, FDV filter, and sort controls |

---

## How to Run

### Prerequisites
- Python 3.11+
- Node.js 18+

### 1. Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

API available at: `http://localhost:8000/api/coins`  
Swagger docs at: `http://localhost:8000/docs`

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

App available at: `http://localhost:3000`

---

## Filters Applied (Backend)

| Filter | Criteria | Status |
|---|---|---|
| Market Cap | > $0 | ✅ Applied |
| Max Supply == Total Supply | Both non-null, float tolerance of 1 | ✅ Applied |
| FDV | < $100,000,000 | ✅ Applied |
| 24h Trading Volume | > $50,000 | ✅ Applied |
| TVL | > $50,000 | ⚠️ Implemented, disabled on free tier — see note |
| Preview Listing | == `true` | ⚠️ Spec contradiction — see note |

---

## Frontend Features

- **Search** — partial match on name or ticker symbol (e.g. `eth` → Ethereum)
- **FDV filter** — user-defined upper bound in millions USD (applied client-side)
- **Sort** — by Market Cap or 24h Volume, ascending or descending

---

## Assumptions & Limitations

### ⚠️ TVL filter — implemented but disabled on free tier

TVL is not returned by `/coins/markets`. It requires a separate call to `/coins/{id}` per coin.

The implementation is complete in `main.py` (`fetch_tvl()` function + enrichment loop) and can be enabled by setting:

```python
ENABLE_TVL_ENRICHMENT = True  # top of main.py
```

However, on the free CoinGecko tier, `/coins/{id}` calls trigger 429 rate-limit errors even with multi-second delays between requests. The free tier enforces a strict ~30 req/min cap shared across all endpoint types — fetching 2 pages of market data already uses a significant portion of that budget.

**With a Pro API key** this works cleanly:
- Update `COINGECKO_BASE` to `https://pro-api.coingecko.com/api/v3`
- Add `"x-cg-pro-api-key": "YOUR_KEY"` to `HEADERS`
- Set `ENABLE_TVL_ENRICHMENT = True`
- The enrichment only runs on the ~20 coins that passed the other filters, so it's just ~20 additional requests — well within Pro rate limits

**Alternative (no Pro key needed):** DeFiLlama offers a free TVL API with no rate limits, cross-referenceable by contract address.

---

### ⚠️ `preview_listing` filter — spec contradiction

After researching the CoinGecko API and documentation, this filter is internally contradictory with the rest of the spec.

CoinGecko defines a **Preview Listing** as a token that has been submitted but has not yet had its Token Generation Event (TGE) — pre-launch, not yet trading, no price or market data.

This directly contradicts the other filters:

| Filter | Implication |
|---|---|
| `preview_listing == true` | Pre-TGE, no trading → mcap = 0, volume = 0 |
| `mcap > 0` | Actively trading |
| `volume > $50k` | Actively trading |
| `TVL > $50k` | Actively trading |

No coin can satisfy both simultaneously. Additionally, the `preview_listing` boolean does not appear in the free-tier `/coins/markets` response at all — it only exists in `/coins/{id}` or via Pro endpoints.

**Decision:** Filter disabled with a clear comment in the code. All other filters are applied correctly. The ~20 coins returned are genuinely filtered, actively-trading low-cap coins.

**With a Pro key:** `/coins/list/new` targets the latest 200 listings directly.

---

### Other Notes

**Pagination:** 2 pages × 250 coins = 500 coins, with a 3s delay between pages to stay within the free-tier rate limit.

**Caching:** Results cached in-memory for 2 minutes. Repeated frontend loads are served instantly.

**CORS:** Open (`*`) for local development. Lock to frontend origin in production.

---

## What I Would Do Next (with more time)

1. **Enable TVL via Pro key or DeFiLlama** — the implementation is already in place, just needs a key or a DeFiLlama integration
2. **Preview listings via `/coins/list/new`** — Pro endpoint that directly targets pre-TGE coins
3. **Frontend pagination** — virtual scroll or paginated table for larger datasets
4. **Better error UX** — rate-limit countdown, auto-retry with progress indicator
5. **Unit tests** — test `passes_basic_filters()` against known coin fixtures
6. **Docker Compose** — single `docker compose up` to run both services

---

## AI Workflow

| Tool | Usage |
|---|---|
| **Claude (claude.ai)** | Generated full backend + frontend scaffold, filter logic, retry/caching strategy, TVL enrichment implementation, README |
| **Gemini** | Cross-checked the `preview_listing` API behaviour, confirmed the spec contradiction |
| **Manual review** | Debugged 502 → 429 → working progression in real terminal output, identified free-tier limits on `/coins/{id}`, tuned retry delays, verified final filter results |

**Where AI helped most:** Boilerplate elimination — FastAPI CORS setup, httpx async patterns, React useMemo filter chain, retry logic. These are patterns I know well but AI produced them in seconds, freeing time for the domain-specific problems.

**What I reviewed/corrected manually:**
- Caught that TVL and `preview_listing` don't exist in the free `/coins/markets` response — rather than silently returning 0 results, disabled both with clear documentation
- Identified that firing 4 concurrent CoinGecko requests triggers immediate 429s — switched to sequential with delays
- Discovered that `/coins/{id}` TVL lookups also 429 on the free tier even with gaps — gated behind `ENABLE_TVL_ENRICHMENT` flag rather than leaving broken code
- Researched CoinGecko docs to understand what "preview listing" actually means, which revealed the spec contradiction
- Verified the ~20 coin result is correct behaviour, not a bug
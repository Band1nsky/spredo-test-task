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
| Preview Listing | == `true` | ⚠️ See note below |
| TVL | > $50,000 | ⚠️ See note below |

---

## Frontend Features

- **Search** — partial match on name or ticker symbol (e.g. `eth` → Ethereum)
- **FDV filter** — user-defined upper bound in millions USD (applied client-side on top of backend data)
- **Sort** — by Market Cap or 24h Volume, ascending or descending, toggled by clicking column headers

---

## Assumptions & Limitations

### ⚠️ The `preview_listing` filter is a spec contradiction

After researching the CoinGecko API and documentation, I discovered that this filter is internally contradictory with the rest of the spec.

CoinGecko defines a **Preview Listing** as a token that has been submitted but has not yet had its Token Generation Event (TGE) — meaning it is pre-launch, not yet trading, and has no price or market data.

This directly contradicts the other filters in the spec:

| Filter | Implication |
|---|---|
| `preview_listing == true` | Pre-TGE, no trading → mcap = 0, volume = 0 |
| `mcap > 0` | Actively trading |
| `volume > $50k` | Actively trading |
| `TVL > $50k` | Actively trading |

**No coin can satisfy both conditions simultaneously.** Applying `preview_listing == true` alongside the market activity filters would always return 0 results.

Additionally, the `preview_listing` boolean does not appear in the free-tier `/coins/markets` response at all — it only exists in the detailed `/coins/{id}` endpoint or via Pro-tier endpoints.

**Decision:** The filter is disabled with a clear comment in the code. All other filters are applied correctly. The current result of ~20 coins reflects genuinely filtered, actively-trading low-cap coins.

**What a Pro API key would unlock:**
- `/coins/list/new` endpoint to specifically target the latest 200 listings
- The `preview_listing` boolean on `/coins/{id}` (but calling this per-coin on 500+ coins exhausts the free rate limit of 30 req/min instantly)

---

### ⚠️ TVL filter disabled

`/coins/markets` does not return TVL. It is available via `/coins/{id}` but the same rate-limit problem applies — enriching 500 coins individually is not feasible on the free tier.

**What I would do with a Pro key or more time:**
- Use DeFiLlama's free API as a TVL data source (no rate-limit issues)
- Fetch TVL for the already-filtered subset only (20 coins instead of 500)

---

### Other Notes

**Pagination:** The backend fetches 2 pages × 250 coins = 500 coins with a 3s delay between pages to respect the free-tier rate limit (~30 req/min).

**Caching:** Results are cached in-memory for 2 minutes. Repeated frontend loads are served instantly without re-hitting CoinGecko.

**CORS:** Open (`*`) for local development. In production this would be locked to the frontend's origin.

---

## What I Would Do Next (with more time)

1. **TVL via DeFiLlama** — Free API, no rate limits, cross-reference by contract address
2. **Preview listings via Pro** — `/coins/list/new` for actual pre-TGE tokens
3. **Frontend pagination** — Virtual scroll or paginated table for larger datasets
4. **Better error UX** — Rate-limit countdown, auto-retry with progress indicator
5. **Unit tests** — Test `passes_filters()` against known coin fixtures
6. **Docker Compose** — Single `docker compose up` to run both services

---

## AI Workflow

| Tool | Usage |
|---|---|
| **Claude (claude.ai)** | Generated full backend + frontend scaffold, filter logic, retry/caching strategy, README |
| **Gemini** | Cross-checked the `preview_listing` API behaviour and confirmed the spec contradiction |
| **Manual review** | Debugged 502→429→working progression, identified TVL/preview_listing issues, tuned retry delays based on real terminal output |

**Where AI helped most:** Boilerplate elimination — FastAPI CORS setup, httpx async patterns, React useMemo filter chain. These are patterns I know well but AI produced them in seconds, freeing time to focus on the domain-specific problems.

**What I reviewed/corrected manually:**
- Identified that TVL and `preview_listing` don't exist in the free API — removed both filters rather than silently returning 0 results
- Caught that firing 4 concurrent CoinGecko requests triggers immediate 429s — switched to sequential with delays
- Researched the CoinGecko docs to understand what "preview listing" actually means, which revealed the spec contradiction
- Verified the final 20/500 result is correct behaviour, not a bug
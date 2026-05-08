# Spredo Take-Home — Full Stack Crypto Dashboard

## What Was Built

| | |
|---|---|
| **Backend** | FastAPI (Python) — fetches CoinGecko `/coins/markets`, applies filters, exposes `GET /api/coins` and `GET /api/coins/tvl` |
| **Frontend** | React + Vite — two-phase loading, displays filtered coins with TVL enrichment, search, FDV filter, and sort controls |

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

## Architecture — Two-Phase Loading

The app uses a two-phase loading strategy to keep the UI responsive despite CoinGecko's rate limits:

**Phase 1 — Immediate (~5s)**  
`GET /api/coins` fetches 500 coins from `/coins/markets`, applies all non-TVL filters, and returns results. The frontend renders the full table as soon as this resolves.

**Phase 2 — Background (runs after table is visible)**  
The frontend passes the filtered coin IDs to `GET /api/coins/tvl?ids=...`. The backend fetches `/coins/{id}` for each coin with 2s gaps to avoid rate limits. TVL cells show `loading…` and update in place as data arrives. A TVL > $50k toggle becomes meaningful once data is loaded.

This approach means the user sees data in ~5 seconds instead of waiting 60+ seconds for TVL enrichment to complete before anything renders.

---

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /api/coins` | Returns filtered coin list (no TVL) |
| `GET /api/coins/tvl?ids=id1,id2,...` | Returns `{ coin_id: tvl_usd }` map for given IDs |
| `GET /health` | Health check |

---

## Filters Applied

| Filter | Criteria | Status |
|---|---|---|
| Market Cap | > $0 | ✅ Applied in `/api/coins` |
| Max Supply == Total Supply | Both non-null, float tolerance of 1 | ✅ Applied in `/api/coins` |
| FDV | < $100,000,000 | ✅ Applied in `/api/coins` |
| 24h Trading Volume | > $50,000 | ✅ Applied in `/api/coins` |
| TVL | > $50,000 | ✅ Applied client-side after `/api/coins/tvl` resolves |
| Preview Listing | == `true` | ⚠️ Spec contradiction — see note below |

---

## Frontend Features

- **Search** — partial match on name or ticker symbol (e.g. `eth` → Ethereum)
- **FDV filter** — user-defined upper bound in millions USD
- **TVL > $50k toggle** — filters out coins below the threshold once TVL data loads
- **Sort** — by Market Cap or 24h Volume, ascending or descending
- **Price formatting** — sub-cent prices shown with 6 decimal places (e.g. `$0.000042`) to avoid misleading `$0` display

---

## Assumptions & Limitations

### ⚠️ `preview_listing` filter — spec contradiction

After researching the CoinGecko API and documentation, this filter is internally contradictory with the rest of the spec.

CoinGecko defines a **Preview Listing** as a token submitted before its Token Generation Event (TGE) — pre-launch, not yet trading, with no price or market data.

This directly contradicts the other filters:

| Filter | Implication |
|---|---|
| `preview_listing == true` | Pre-TGE, no trading → mcap = 0, volume = 0 |
| `mcap > 0` | Actively trading |
| `volume > $50k` | Actively trading |
| `TVL > $50k` | Actively trading |

No coin can satisfy both simultaneously. The field also does not appear in the free-tier `/coins/markets` response. The filter is present in `passes_basic_filters()` as a commented-out line with an explanation:

```python
# if coin.get("preview_listing") == True: return False  ← always 0 results
```

**With a Pro key:** `/coins/list/new` directly targets the latest 200 listings.

---

### TVL — fetched via background endpoint

TVL is not available in `/coins/markets`. The solution fetches it via a dedicated `/api/coins/tvl` endpoint that calls `/coins/{id}` for the filtered subset only (~20 coins).

On the free tier, these calls still occasionally hit 429s. The backend handles this gracefully — a rate-limited coin gets `null` TVL and remains visible in the table rather than blocking the response. The TVL filter toggle in the UI only removes coins where TVL is explicitly known to be below $50k.

**With a Pro key:** update `COINGECKO_BASE` to `https://pro-api.coingecko.com/api/v3` and add `"x-cg-pro-api-key": "YOUR_KEY"` to `HEADERS`. Rate limits are high enough that 429s stop being an issue entirely.

---

### Other Notes

**Pagination:** 2 pages × 250 coins = 500 coins, with a 3s delay between pages.

**Caching:** Both endpoints cache results for 2 minutes in memory. Repeated loads are served instantly without re-hitting CoinGecko.

**CORS:** Open (`*`) for local development. Lock to the frontend's origin in production.

---

## What I Would Do Next (with more time)

1. **DeFiLlama for TVL** — free API, no rate limits, cross-reference by contract address; eliminates the 429 problem on TVL entirely
2. **Preview listings via `/coins/list/new`** — Pro endpoint that directly targets pre-TGE tokens
3. **Frontend pagination** — virtual scroll or paginated table for larger datasets
4. **Better error UX** — per-cell retry button for TVL, rate-limit countdown
5. **Unit tests** — test `passes_basic_filters()` against known coin fixtures
6. **Docker Compose** — single `docker compose up` to run both services

---

## AI Workflow

### Tools Used
- **Claude (claude.ai)** — primary tool throughout
- **Gemini** — used for cross-checking API behaviour and spec interpretation

---

### How Claude Was Used

The entire project was scaffolded and iterated on through a single Claude conversation. Rather than using it as a one-shot code generator, it was used as a pair programmer — each problem that came up in the terminal was fed back in and debugged collaboratively.

**Initial scaffold (~10 min)**  
Claude generated the full project structure in one pass: FastAPI app with CORS, httpx async fetching, filter logic, React frontend with `useMemo` for client-side filtering/sorting, Vite config, and a first-draft README. This eliminated all boilerplate and let the session focus immediately on domain-specific problems.

**Debugging the CoinGecko rate limits (~20 min)**  
The first run produced a `502 Bad Gateway`. The uvicorn log was pasted into Claude, which identified two root causes: the default `httpx` User-Agent being blocked by CoinGecko, and firing 4 concurrent requests exhausting the free-tier rate limit. Claude rewrote the fetch logic to add a browser User-Agent header and switch from `asyncio.gather` (concurrent) to sequential fetching with delays. A second run produced `429 Too Many Requests` — the delays were still too short. Claude increased them to 10s+ backoff and the fetches succeeded.

**Identifying the filter contradiction (~15 min)**  
After the backend worked, the frontend showed "0 of 0 coins". Claude identified that the TVL filter was the culprit — `/coins/markets` doesn't return TVL, so it defaulted to 0 and every coin failed `tvl > $50k`. This prompted deeper research: Gemini was used to cross-check CoinGecko's documentation on what `preview_listing` actually means, which revealed the spec contradiction. Both filters were disabled with documented reasoning rather than silently returning empty results.

**TVL enrichment via `/coins/{id}` (~15 min)**  
After finding CoinGecko's documentation showing TVL is available on `/coins/{id}`, Claude implemented a TVL enrichment step — fetching it for the filtered subset only (~20 coins) rather than all 500. This was enabled on the backend and tested, but hit 429s again. Claude's first fix was graceful failure (return `None` on 429 rather than retrying), but the evaluation feedback suggested showing partial data is better than disabling the feature entirely.

**Two-phase loading architecture (~10 min)**  
The final iteration split the backend into two endpoints — `/api/coins` (fast, no TVL) and `/api/coins/tvl` (slow, background). The frontend was updated to render the table immediately from phase 1, then fire phase 2 in the background and update TVL cells in place as data arrived. This was a direct response to the UX problem of a 60+ second blank screen.

---

### Where AI Helped Most

- **Boilerplate elimination** — FastAPI middleware, httpx async patterns, React `useMemo` chains, retry logic with exponential backoff. These are well-understood patterns that would have taken 20-30 minutes to write manually; Claude produced them in seconds.
- **Debugging from terminal output** — pasting raw uvicorn logs and getting a specific diagnosis (User-Agent block, concurrent request burst) was faster than reading documentation.
- **README structure** — the table-based format for filters and AI workflow was suggested by Claude and made the document significantly easier to scan.

---

### What Was Reviewed and Corrected Manually

- **The `preview_listing` contradiction** — Claude initially tried to implement the filter against a field that doesn't exist. The decision to disable it and document why came from manually reading the CoinGecko support documentation and cross-checking with Gemini.
- **TVL approach** — Claude's first instinct was to fetch TVL for all 500 coins concurrently. The decision to fetch only for the already-filtered subset, and later to split it into a separate background endpoint, came from reasoning about rate limits and UX rather than from AI output.
- **Delay tuning** — the specific sleep durations (3s between pages, 2s between TVL calls) were arrived at through real trial-and-error in the terminal, not from AI suggestions.
- **Filter correctness** — verified each threshold against the spec manually: `>` vs `>=`, `$100M` boundary, float tolerance on supply equality.
- **The two-phase loading decision** — came from recognising that a 60-second blank screen is a worse UX than a table that loads fast with a TVL column that fills in slowly. This was a product judgment call, not a code suggestion.
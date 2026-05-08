import { useState, useEffect, useMemo } from "react";

const API_BASE = "http://localhost:8000";

const fmt = (n, opts = {}) =>
  n == null ? "—" : new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2, ...opts }).format(n);

const fmtUsd = (n) => {
  if (n == null) return "—";
  if (n < 0.01) return "$" + n.toFixed(6);  // dust prices e.g. $0.000042
  if (n < 1)    return "$" + n.toFixed(4);  // sub-dollar  e.g. $0.0812
  return "$" + fmt(n);
};

const pctColor = (v) => (v == null ? "#888" : v >= 0 ? "#22c55e" : "#ef4444");

export default function App() {
  const [coins, setCoins]       = useState([]);
  const [tvlMap, setTvlMap]     = useState({});   // { [coin_id]: usd | null }
  const [tvlLoading, setTvlLoading] = useState(false);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState(null);

  const [search, setSearch]     = useState("");
  const [maxFdv, setMaxFdv]     = useState("");
  const [minTvl, setMinTvl]     = useState(false);  // toggle: hide coins with no TVL
  const [sortBy, setSortBy]     = useState("market_cap");
  const [sortDir, setSortDir]   = useState("desc");

  // Phase 1: fetch coins immediately
  useEffect(() => {
    fetch(`${API_BASE}/api/coins`)
      .then((r) => { if (!r.ok) throw new Error(`Server error ${r.status}`); return r.json(); })
      .then((data) => {
        setCoins(data.coins);
        setLoading(false);
        // Phase 2: fetch TVL in background once we have the coin IDs
        if (data.coins.length > 0) {
          const ids = data.coins.map((c) => c.id).join(",");
          setTvlLoading(true);
          fetch(`${API_BASE}/api/coins/tvl?ids=${ids}`)
            .then((r) => r.json())
            .then((tvl) => setTvlMap(tvl))
            .catch(() => {})
            .finally(() => setTvlLoading(false));
        }
      })
      .catch((e) => { setError(e.message); setLoading(false); });
  }, []);

  const displayed = useMemo(() => {
    let list = [...coins];

    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter((c) => c.name.toLowerCase().includes(q) || c.symbol.toLowerCase().includes(q));
    }

    if (maxFdv !== "") {
      const cap = parseFloat(maxFdv) * 1_000_000;
      if (!isNaN(cap)) list = list.filter((c) => (c.fully_diluted_valuation ?? Infinity) < cap);
    }

    if (minTvl) {
      list = list.filter((c) => (tvlMap[c.id] ?? 0) > 50_000);
    }

    list.sort((a, b) => {
      const av = a[sortBy] ?? 0;
      const bv = b[sortBy] ?? 0;
      return sortDir === "desc" ? bv - av : av - bv;
    });

    return list;
  }, [coins, search, maxFdv, minTvl, sortBy, sortDir, tvlMap]);

  const toggleSort = (field) => {
    if (sortBy === field) setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    else { setSortBy(field); setSortDir("desc"); }
  };

  const SortIcon = ({ field }) =>
    sortBy !== field ? <span style={{ opacity: 0.3 }}>⇅</span> : <span>{sortDir === "desc" ? "↓" : "↑"}</span>;

  const TvlCell = ({ coinId }) => {
    if (tvlLoading && tvlMap[coinId] === undefined)
      return <span style={{ color: "#64748b", fontSize: "0.75rem" }}>loading…</span>;
    const val = tvlMap[coinId];
    return <span>{fmtUsd(val)}</span>;
  };

  return (
    <div style={styles.page}>
      <header style={styles.header}>
        <h1 style={styles.title}><span style={styles.titleAccent}>⬡</span> Spredo Crypto</h1>
        <p style={styles.subtitle}>Filtered · Low-cap · Pre-market projects</p>
      </header>

      <div style={styles.controls}>
        <input
          style={styles.input}
          placeholder="Search by name or symbol…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <div style={styles.fdvWrap}>
          <span style={styles.label}>Max FDV</span>
          <input
            style={{ ...styles.input, width: 160 }}
            type="number"
            placeholder="e.g. 50  (M USD)"
            value={maxFdv}
            onChange={(e) => setMaxFdv(e.target.value)}
          />
        </div>
        <div style={styles.fdvWrap}>
          <span style={styles.label}>TVL &gt; $50k</span>
          <button
            style={{ ...styles.sortBtn, ...(minTvl ? styles.sortBtnActive : {}) }}
            onClick={() => setMinTvl((v) => !v)}
            title="Only show coins with TVL above $50k"
          >
            {minTvl ? "ON" : "OFF"}
          </button>
        </div>
        <div style={styles.sortBtns}>
          <button style={{ ...styles.sortBtn, ...(sortBy === "market_cap" ? styles.sortBtnActive : {}) }} onClick={() => toggleSort("market_cap")}>
            MCap <SortIcon field="market_cap" />
          </button>
          <button style={{ ...styles.sortBtn, ...(sortBy === "total_volume" ? styles.sortBtnActive : {}) }} onClick={() => toggleSort("total_volume")}>
            Volume <SortIcon field="total_volume" />
          </button>
        </div>
      </div>

      <div style={styles.statusBar}>
        {loading && <span>Loading from backend…</span>}
        {error && <span style={{ color: "#ef4444" }}>Error: {error}</span>}
        {!loading && !error && (
          <span>
            Showing <strong>{displayed.length}</strong> of <strong>{coins.length}</strong> coins
            {tvlLoading && <span style={{ color: "#a78bfa", marginLeft: "0.75rem" }}>⟳ fetching TVL…</span>}
          </span>
        )}
      </div>

      {!loading && !error && (
        <div style={styles.tableWrap}>
          <table style={styles.table}>
            <thead>
              <tr>
                {["#", "Project", "Price", "MCap", "FDV", "24h Volume", "24h %", "TVL"].map((h) => (
                  <th key={h} style={styles.th}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {displayed.length === 0 && (
                <tr><td colSpan={8} style={{ ...styles.td, textAlign: "center", color: "#888", padding: "2rem" }}>No coins match your filters.</td></tr>
              )}
              {displayed.map((c, i) => (
                <tr key={c.id} style={styles.row}>
                  <td style={{ ...styles.td, color: "#888", width: 36 }}>{i + 1}</td>
                  <td style={styles.td}>
                    <div style={styles.coinCell}>
                      {c.image && <img src={c.image} alt="" style={styles.coinImg} />}
                      <div>
                        <div style={styles.coinName}>{c.name}</div>
                        <div style={styles.coinSymbol}>{c.symbol}</div>
                      </div>
                    </div>
                  </td>
                  <td style={styles.td}>{fmtUsd(c.current_price)}</td>
                  <td style={styles.td}>{fmtUsd(c.market_cap)}</td>
                  <td style={styles.td}>{fmtUsd(c.fully_diluted_valuation)}</td>
                  <td style={styles.td}>{fmtUsd(c.total_volume)}</td>
                  <td style={{ ...styles.td, color: pctColor(c.price_change_percentage_24h), fontWeight: 600 }}>
                    {c.price_change_percentage_24h != null
                      ? (c.price_change_percentage_24h >= 0 ? "+" : "") + c.price_change_percentage_24h.toFixed(2) + "%"
                      : "—"}
                  </td>
                  <td style={styles.td}><TvlCell coinId={c.id} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

const styles = {
  page:         { minHeight: "100vh", background: "#0a0a0f", color: "#e2e8f0", fontFamily: "'DM Mono', 'Fira Code', monospace", padding: "0 0 4rem" },
  header:       { padding: "2.5rem 2rem 1.5rem", borderBottom: "1px solid #1e1e2e" },
  title:        { margin: 0, fontSize: "1.8rem", fontWeight: 700, letterSpacing: "-0.03em", fontFamily: "'Space Grotesk', 'DM Mono', monospace" },
  titleAccent:  { color: "#a78bfa", marginRight: "0.4rem" },
  subtitle:     { margin: "0.3rem 0 0", color: "#64748b", fontSize: "0.85rem" },
  controls:     { display: "flex", flexWrap: "wrap", gap: "0.75rem", padding: "1.25rem 2rem", alignItems: "center", borderBottom: "1px solid #1e1e2e" },
  input:        { background: "#13131f", border: "1px solid #2d2d44", borderRadius: 6, color: "#e2e8f0", padding: "0.5rem 0.85rem", fontSize: "0.85rem", outline: "none", flex: 1, minWidth: 200, fontFamily: "inherit" },
  fdvWrap:      { display: "flex", alignItems: "center", gap: "0.5rem" },
  label:        { color: "#64748b", fontSize: "0.8rem", whiteSpace: "nowrap" },
  sortBtns:     { display: "flex", gap: "0.5rem" },
  sortBtn:      { background: "#13131f", border: "1px solid #2d2d44", borderRadius: 6, color: "#94a3b8", padding: "0.45rem 0.9rem", fontSize: "0.8rem", cursor: "pointer", fontFamily: "inherit" },
  sortBtnActive:{ borderColor: "#a78bfa", color: "#a78bfa" },
  statusBar:    { padding: "0.6rem 2rem", fontSize: "0.8rem", color: "#64748b", borderBottom: "1px solid #1e1e2e" },
  tableWrap:    { overflowX: "auto", padding: "0 1rem" },
  table:        { width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" },
  th:           { textAlign: "left", padding: "0.75rem 1rem", color: "#64748b", fontWeight: 500, borderBottom: "1px solid #1e1e2e", whiteSpace: "nowrap" },
  td:           { padding: "0.7rem 1rem", borderBottom: "1px solid #0f0f1a" },
  row:          { transition: "background 0.1s" },
  coinCell:     { display: "flex", alignItems: "center", gap: "0.65rem" },
  coinImg:      { width: 28, height: 28, borderRadius: "50%" },
  coinName:     { fontWeight: 600, fontSize: "0.87rem" },
  coinSymbol:   { color: "#64748b", fontSize: "0.75rem" },
};
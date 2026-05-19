// ============================================================
//  MAIN.JS — SOL Momentum Surge Dashboard
//  Maneja: API polling · Gráficos · UI dinámica
// ============================================================

"use strict";

// ── CONFIG ──────────────────────────────────────────────────
const API_BASE       = "";           // mismo origen que Flask
const POLL_STATUS_MS = 5000;         // actualizar estado cada 5s
const POLL_CHART_MS  = 30000;        // actualizar gráficos cada 30s

// ── ESTADO LOCAL ────────────────────────────────────────────
let priceChart   = null;
let rsiChart     = null;
let macdChart    = null;
let volumeChart  = null;
let lastPrice    = null;

// ── UTILS ────────────────────────────────────────────────────

function $(id) { return document.getElementById(id); }

function formatUSDT(v) {
  return typeof v === "number" ? `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 4 })}` : "—";
}

function formatPct(v) {
  if (typeof v !== "number") return "—";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

function colorPct(el, v) {
  el.className = "stat-value " + (v > 0 ? "positive" : v < 0 ? "negative" : "neutral");
}

function toast(msg, type = "info") {
  const container = $("toast-container");
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

function timeAgo(isoString) {
  if (!isoString) return "—";
  const d = new Date(isoString + (isoString.endsWith("Z") ? "" : "Z"));
  const diff = Math.floor((Date.now() - d.getTime()) / 1000);
  if (diff < 60) return `hace ${diff}s`;
  if (diff < 3600) return `hace ${Math.floor(diff / 60)}m`;
  return d.toLocaleTimeString("es-AR");
}

// ── FETCH HELPERS ────────────────────────────────────────────

async function apiFetch(path, options = {}) {
  const res = await fetch(API_BASE + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  return res.json();
}

// ── CHART: PRICE ─────────────────────────────────────────────

function buildPriceChart(data) {
  const ctx = $("price-chart").getContext("2d");

  const labels = data.timestamps.map(t => new Date(t));
  const closes = data.close;
  const emaFast = data.ema_fast;
  const emaSlow = data.ema_slow;

  const lineGreen = "rgba(0,230,118,";
  const lineAmber = "rgba(240,165,0,";
  const lineCyan  = "rgba(0,212,200,";

  if (priceChart) priceChart.destroy();

  priceChart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Precio",
          data: closes,
          borderColor: "rgba(212,228,244,0.7)",
          borderWidth: 1.5,
          pointRadius: 0,
          tension: 0.2,
          fill: false,
          order: 1,
        },
        {
          label: "EMA 9",
          data: emaFast,
          borderColor: lineGreen + "0.9)",
          borderWidth: 1.5,
          pointRadius: 0,
          tension: 0.3,
          fill: false,
          order: 2,
        },
        {
          label: "EMA 21",
          data: emaSlow,
          borderColor: lineAmber + "0.9)",
          borderWidth: 1.5,
          pointRadius: 0,
          tension: 0.3,
          fill: false,
          order: 3,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 400 },
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: {
          labels: { color: "#6b8aa8", font: { family: "Space Mono", size: 10 }, boxWidth: 12 }
        },
        tooltip: {
          backgroundColor: "#0d1117",
          borderColor: "#1e2a38",
          borderWidth: 1,
          titleColor: "#d4e4f4",
          bodyColor: "#6b8aa8",
          titleFont: { family: "Space Mono", size: 10 },
          bodyFont:  { family: "Space Mono", size: 10 },
          callbacks: {
            label: ctx => ` ${ctx.dataset.label}: $${ctx.parsed.y?.toFixed(4)}`,
          }
        },
      },
      scales: {
        x: {
          type: "time",
          time: { unit: "minute", displayFormats: { minute: "HH:mm" } },
          ticks: { color: "#3a5268", font: { size: 9 }, maxTicksLimit: 10 },
          grid: { color: "rgba(30,42,56,0.5)" },
        },
        y: {
          ticks: { color: "#3a5268", font: { family: "Space Mono", size: 9 }, callback: v => `$${v.toFixed(2)}` },
          grid: { color: "rgba(30,42,56,0.5)" },
        },
      },
    },
  });
}

// ── CHART: RSI ───────────────────────────────────────────────

function buildRSIChart(data) {
  const ctx = $("rsi-chart").getContext("2d");
  const labels = data.timestamps.map(t => new Date(t));

  if (rsiChart) rsiChart.destroy();

  rsiChart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "RSI 14",
          data: data.rsi,
          borderColor: "rgba(0,212,200,0.9)",
          borderWidth: 1.5,
          pointRadius: 0,
          fill: false,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 400 },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: "#0d1117",
          borderColor: "#1e2a38",
          borderWidth: 1,
          bodyColor: "#6b8aa8",
          bodyFont: { family: "Space Mono", size: 10 },
          callbacks: { label: ctx => ` RSI: ${ctx.parsed.y?.toFixed(2)}` }
        },
        annotation: {},
      },
      scales: {
        x: {
          type: "time",
          time: { unit: "minute", displayFormats: { minute: "HH:mm" } },
          ticks: { color: "#3a5268", font: { size: 9 }, maxTicksLimit: 8 },
          grid: { color: "rgba(30,42,56,0.3)" },
        },
        y: {
          min: 0,
          max: 100,
          ticks: {
            color: "#3a5268",
            font: { family: "Space Mono", size: 9 },
            callback: v => v,
            stepSize: 25,
          },
          grid: { color: "rgba(30,42,56,0.3)" },
        },
      },
    },
  });
}

// ── CHART: MACD ──────────────────────────────────────────────

function buildMACDChart(data) {
  const ctx = $("macd-chart").getContext("2d");
  const labels = data.timestamps.map(t => new Date(t));

  const histColors = data.macd_hist.map(v =>
    v === null ? "transparent" : v >= 0 ? "rgba(0,230,118,0.6)" : "rgba(255,61,87,0.6)"
  );

  if (macdChart) macdChart.destroy();

  macdChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          type: "line",
          label: "MACD",
          data: data.macd,
          borderColor: "rgba(0,212,200,0.9)",
          borderWidth: 1.5,
          pointRadius: 0,
          fill: false,
          order: 1,
        },
        {
          type: "line",
          label: "Signal",
          data: data.macd_signal,
          borderColor: "rgba(240,165,0,0.9)",
          borderWidth: 1.5,
          pointRadius: 0,
          fill: false,
          order: 2,
        },
        {
          type: "bar",
          label: "Hist",
          data: data.macd_hist,
          backgroundColor: histColors,
          borderWidth: 0,
          order: 3,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 400 },
      plugins: {
        legend: {
          labels: { color: "#6b8aa8", font: { family: "Space Mono", size: 9 }, boxWidth: 10 }
        },
        tooltip: {
          backgroundColor: "#0d1117",
          borderColor: "#1e2a38",
          borderWidth: 1,
          bodyColor: "#6b8aa8",
          bodyFont: { family: "Space Mono", size: 10 },
        },
      },
      scales: {
        x: {
          type: "time",
          time: { unit: "minute", displayFormats: { minute: "HH:mm" } },
          ticks: { color: "#3a5268", font: { size: 9 }, maxTicksLimit: 8 },
          grid: { color: "rgba(30,42,56,0.3)" },
        },
        y: {
          ticks: { color: "#3a5268", font: { family: "Space Mono", size: 9 } },
          grid: { color: "rgba(30,42,56,0.3)" },
        },
      },
    },
  });
}

// ── CHART: VOLUME ────────────────────────────────────────────

function buildVolumeChart(data) {
  const ctx = $("volume-chart").getContext("2d");
  const labels = data.timestamps.map(t => new Date(t));

  const volColors = data.volume_ratio.map(r =>
    r === null ? "rgba(30,42,56,0.5)" :
    r >= 1.5   ? "rgba(240,165,0,0.7)" : "rgba(30,42,56,0.8)"
  );

  if (volumeChart) volumeChart.destroy();

  volumeChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "Volumen",
          data: data.volume,
          backgroundColor: volColors,
          borderWidth: 0,
          order: 2,
        },
        {
          type: "line",
          label: "Vol SMA 20",
          data: data.volume_sma,
          borderColor: "rgba(0,212,200,0.7)",
          borderWidth: 1.5,
          pointRadius: 0,
          fill: false,
          order: 1,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 400 },
      plugins: {
        legend: {
          labels: { color: "#6b8aa8", font: { family: "Space Mono", size: 9 }, boxWidth: 10 }
        },
        tooltip: {
          backgroundColor: "#0d1117",
          borderColor: "#1e2a38",
          borderWidth: 1,
          bodyColor: "#6b8aa8",
          bodyFont: { family: "Space Mono", size: 10 },
        },
      },
      scales: {
        x: {
          type: "time",
          time: { unit: "minute", displayFormats: { minute: "HH:mm" } },
          ticks: { color: "#3a5268", font: { size: 9 }, maxTicksLimit: 8 },
          grid: { display: false },
        },
        y: {
          ticks: { color: "#3a5268", font: { family: "Space Mono", size: 9 }, maxTicksLimit: 4 },
          grid: { color: "rgba(30,42,56,0.3)" },
        },
      },
    },
  });
}

// ── UPDATE STATUS UI ─────────────────────────────────────────

function updateStatus(data) {
  if (!data.ok) {
    $("last-error").textContent = data.error || "Error desconocido";
    return;
  }

  const { market, portfolio, config: cfg, bot_running, last_signal, scan_count, last_error } = data;

  // Precio
  const priceEl = $("current-price");
  const newPrice = market.price;
  if (lastPrice !== null && lastPrice !== newPrice) {
    priceEl.style.color = newPrice > lastPrice ? "var(--green)" : "var(--red)";
    setTimeout(() => { priceEl.style.color = ""; }, 800);
  }
  priceEl.textContent = formatUSDT(newPrice);
  lastPrice = newPrice;

  const chEl = $("price-change");
  const ch = market.change_24h_pct;
  chEl.textContent = formatPct(ch);
  chEl.className = "price-change " + (ch > 0 ? "positive" : ch < 0 ? "negative" : "neutral");

  $("high-24h").textContent = formatUSDT(market.high_24h);
  $("low-24h").textContent  = formatUSDT(market.low_24h);
  $("vol-24h").textContent  = market.volume_24h?.toLocaleString("en-US", { maximumFractionDigits: 0 }) + " SOL";
  $("change-24h").textContent = formatPct(ch);
  colorPct($("change-24h"), ch);

  // Bot status
  const dot     = $("status-dot");
  const txt     = $("bot-status-text");
  const btnStart = $("btn-start");
  const btnStop  = $("btn-stop");
  if (bot_running) {
    dot.classList.add("running");
    txt.textContent = "CORRIENDO";
    btnStart.disabled = true;
    btnStop.disabled  = false;
  } else {
    dot.classList.remove("running");
    txt.textContent = "DETENIDO";
    btnStart.disabled = false;
    btnStop.disabled  = true;
  }

  // Señal
  const sig     = last_signal?.signal || "FLAT";
  const sigEl   = $("signal-value");
  const bannerEl = $("signal-banner");
  sigEl.textContent = sig;
  sigEl.className   = `signal-value ${sig}`;
  bannerEl.className = `signal-banner signal-${sig}`;
  $("signal-time").textContent = timeAgo(last_signal?.timestamp);

  // Portfolio
  const cap = portfolio.capital_current;
  $("capital-value").textContent = formatUSDT(cap);

  const pnlTotal = portfolio.total_pnl_usdt;
  const pnlTotalEl = $("pnl-total");
  pnlTotalEl.textContent = `${formatPct(portfolio.total_pnl_pct)} (${pnlTotal >= 0 ? "+" : ""}${pnlTotal?.toFixed(2)} USDT)`;
  colorPct(pnlTotalEl, pnlTotal);

  const pnlDay = portfolio.daily_pnl_usdt;
  const pnlDayEl = $("pnl-daily");
  pnlDayEl.textContent = `${formatPct(portfolio.daily_pnl_pct)} (${pnlDay >= 0 ? "+" : ""}${pnlDay?.toFixed(2)} USDT)`;
  colorPct(pnlDayEl, pnlDay);

  $("win-rate").textContent    = `${portfolio.win_rate}%`;
  $("total-trades").textContent = portfolio.total_trades;
  $("win-trades").textContent  = portfolio.winning_trades;
  $("lose-trades").textContent = portfolio.losing_trades;

  // Sistema
  $("scan-count").textContent = scan_count || 0;
  $("last-error").textContent = last_error || "—";
  $("last-update").textContent = new Date().toLocaleTimeString("es-AR");

  // Posición abierta
  const pos = portfolio.open_position;
  const posBar = $("open-pos-bar");
  if (pos) {
    posBar.style.display = "flex";
    const badge = $("pos-badge");
    badge.textContent = pos.side;
    badge.className   = `pos-badge ${pos.side}`;
    $("pos-entry").textContent = formatUSDT(pos.entry_price);
    $("pos-size").textContent  = pos.position_size;
    $("pos-tp").textContent    = formatUSDT(pos.take_profit);
    $("pos-sl").textContent    = formatUSDT(pos.stop_loss);

    const pnlPct = pos.side === "LONG"
      ? (market.price - pos.entry_price) / pos.entry_price
      : (pos.entry_price - market.price) / pos.entry_price;
    const pnlEl = $("pos-pnl");
    pnlEl.textContent = formatPct(pnlPct * 100);
    pnlEl.className   = pnlPct >= 0 ? "positive" : "negative";
  } else {
    posBar.style.display = "none";
  }

  // Historial de trades
  updateTradeList(portfolio.trade_history || []);
}

// ── UPDATE TRADE LIST ────────────────────────────────────────

function updateTradeList(trades) {
  const list = $("trade-list");
  if (!trades || trades.length === 0) {
    list.innerHTML = `<div class="trade-empty">Sin operaciones aún</div>`;
    return;
  }

  list.innerHTML = [...trades].reverse().map(t => `
    <div class="trade-item">
      <span class="trade-badge ${t.side}">${t.side}</span>
      <span style="color:var(--text-secondary);font-size:.65rem">${t.exit_reason}</span>
      <span class="trade-pnl ${t.pnl_usdt >= 0 ? "positive" : "negative"}">
        ${t.pnl_usdt >= 0 ? "+" : ""}${t.pnl_usdt?.toFixed(2)} USDT
      </span>
    </div>
  `).join("");
}

// ── UPDATE INDICATORS ────────────────────────────────────────

function updateSignalIndicators(signal) {
  if (!signal?.ok) return;
  const ind = signal.signal?.indicators;
  const cl  = signal.signal?.conditions_long;
  const cs  = signal.signal?.conditions_short;
  if (!ind) return;

  $("ind-ema-fast").textContent = formatUSDT(ind.ema_fast);
  $("ind-ema-slow").textContent = formatUSDT(ind.ema_slow);
  $("ind-rsi").textContent      = ind.rsi?.toFixed(2);
  $("ind-macd").textContent     = ind.macd?.toFixed(4);
  $("ind-macd-sig").textContent = ind.macd_signal?.toFixed(4);
  $("ind-vol-ratio").textContent = `${ind.volume_ratio?.toFixed(2)}x`;
  $("vol-ratio-tag").textContent = `${ind.volume_ratio?.toFixed(2)}x`;

  // RSI bar
  const rsiPct = Math.min(100, Math.max(0, ind.rsi || 0));
  $("rsi-bar").style.width = rsiPct + "%";

  // Conditions LONG
  setCondition("cond-golden",  cl?.golden_cross);
  setCondition("cond-rsi-up",  cl?.rsi_above_min);
  setCondition("cond-rsi-ob",  cl?.rsi_not_overbought);
  setCondition("cond-vol-l",   cl?.volume_surge);
  setCondition("cond-macd-l",  cl?.macd_bullish);

  // Conditions SHORT
  setCondition("cond-death",   cs?.death_cross);
  setCondition("cond-rsi-dn",  cs?.rsi_below_max);
  setCondition("cond-rsi-os",  cs?.rsi_not_oversold);
  setCondition("cond-vol-s",   cs?.volume_surge);
  setCondition("cond-macd-s",  cs?.macd_bearish);
}

function setCondition(id, met) {
  const el   = $(id);
  const icon = el.querySelector(".cond-icon");
  if (met) {
    el.classList.add("met");
    el.classList.remove("miss");
    icon.textContent = "●";
  } else {
    el.classList.remove("met");
    el.classList.add("miss");
    icon.textContent = "○";
  }
}

// ── BOT CONTROLS ─────────────────────────────────────────────

$("btn-start").addEventListener("click", async () => {
  const res = await apiFetch("/api/bot/start", { method: "POST" });
  toast(res.message || "Bot iniciado", res.ok ? "success" : "error");
  pollStatus();
});

$("btn-stop").addEventListener("click", async () => {
  const res = await apiFetch("/api/bot/stop", { method: "POST" });
  toast(res.message || "Bot detenido", res.ok ? "info" : "error");
  pollStatus();
});

$("btn-long").addEventListener("click", async () => {
  const res = await apiFetch("/api/trade/open", {
    method: "POST",
    body: JSON.stringify({ side: "LONG" }),
  });
  toast(
    res.ok ? `LONG abierto @ $${res.position?.entry_price}` : res.error,
    res.ok ? "success" : "error"
  );
  pollStatus();
});

$("btn-short").addEventListener("click", async () => {
  const res = await apiFetch("/api/trade/open", {
    method: "POST",
    body: JSON.stringify({ side: "SHORT" }),
  });
  toast(
    res.ok ? `SHORT abierto @ $${res.position?.entry_price}` : res.error,
    res.ok ? "success" : "error"
  );
  pollStatus();
});

$("btn-close-trade").addEventListener("click", async () => {
  const res = await apiFetch("/api/trade/close", { method: "POST" });
  toast(
    res.ok ? `Cerrado: ${res.trade?.pnl_pct >= 0 ? "+" : ""}${res.trade?.pnl_pct}%` : res.error,
    res.ok ? (res.trade?.pnl_usdt >= 0 ? "success" : "error") : "error"
  );
  pollStatus();
});

$("btn-reset").addEventListener("click", async () => {
  if (!confirm("¿Resetear paper trading? Se perderá todo el historial.")) return;
  const res = await apiFetch("/api/reset", { method: "POST" });
  toast(res.message || "Reseteado", res.ok ? "info" : "error");
  pollStatus();
});

// ── POLLING LOOPS ────────────────────────────────────────────

async function pollStatus() {
  try {
    const data = await apiFetch("/api/status");
    updateStatus(data);
  } catch (e) {
    console.error("Error en /api/status:", e);
  }
}

async function pollSignal() {
  try {
    const sig = await apiFetch("/api/signal");
    updateSignalIndicators(sig);
  } catch (e) {
    console.error("Error en /api/signal:", e);
  }
}

async function pollCharts() {
  try {
    const res = await apiFetch("/api/chart");
    if (res.ok) {
      buildPriceChart(res.data);
      buildRSIChart(res.data);
      buildMACDChart(res.data);
      buildVolumeChart(res.data);
    }
  } catch (e) {
    console.error("Error en /api/chart:", e);
  }
}

// ── INIT ─────────────────────────────────────────────────────

async function init() {
  toast("Iniciando dashboard...", "info");
  await pollStatus();
  await pollSignal();
  await pollCharts();

  setInterval(pollStatus, POLL_STATUS_MS);
  setInterval(pollSignal, POLL_STATUS_MS);
  setInterval(pollCharts, POLL_CHART_MS);
}

document.addEventListener("DOMContentLoaded", init);

/* ===================================================
   Swedish Dev Scraper – Frontend App
   Reads JSON data from ../data/latest/all.json
   =================================================== */

// Works from docs/ on GitHub Pages: data/ is at repo root, served at same origin
const DATA_URL = "../data/latest/all.json";
const INDEX_URL = "../data/index.json";
const HISTORY_BASE = "../data/snapshots";

const STATUS_LABELS = {
  selling:   "Till salu",
  planning:  "Kommande",
  sold_out:  "Slutsåld",
  completed: "Inflyttad",
  unknown:   "Okänd",
};

const DEVELOPER_COLORS = [
  "#1a56db","#0d9488","#d97706","#7c3aed","#dc2626","#059669","#0891b2",
];

// ── State ──────────────────────────────────────────
let allProjects = [];
let filteredProjects = [];
let sortCol = "developer";
let sortDir = "asc";
let charts = {};

// ── Bootstrap ──────────────────────────────────────
(async () => {
  try {
    const [data, index] = await Promise.all([
      fetchJSON(DATA_URL).catch(() => null),
      fetchJSON(INDEX_URL).catch(() => null),
    ]);

    if (!data) {
      showError("Ingen data tillgänglig ännu. Kör scrapern för att generera data.");
      return;
    }

    allProjects = extractProjects(data);
    renderLastUpdated(data.scraped_at);
    renderSummary(data);
    populateFilters(allProjects);
    applyFilters();
    renderCharts(allProjects);
    renderHistory(index);

    // Wire up filter events
    ["filter-developer","filter-status","filter-search"].forEach(id => {
      document.getElementById(id).addEventListener("input", applyFilters);
    });

    // Sortable headers
    document.querySelectorAll("th.sortable").forEach(th => {
      th.addEventListener("click", () => {
        const col = th.dataset.col;
        if (sortCol === col) sortDir = sortDir === "asc" ? "desc" : "asc";
        else { sortCol = col; sortDir = "asc"; }
        document.querySelectorAll("th.sortable").forEach(h => h.classList.remove("sort-asc","sort-desc"));
        th.classList.add(sortDir === "asc" ? "sort-asc" : "sort-desc");
        renderTable(filteredProjects);
      });
    });

  } catch (err) {
    showError(`Fel vid laddning: ${err.message}`);
    console.error(err);
  }
})();

// ── Data helpers ───────────────────────────────────
async function fetchJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${url}`);
  return r.json();
}

function extractProjects(data) {
  const projects = [];
  const devs = data.developers || {};
  for (const [devName, devData] of Object.entries(devs)) {
    for (const p of (devData.projects || [])) {
      projects.push({ ...p, developer: devName });
    }
  }
  return projects;
}

// ── Render: last updated ───────────────────────────
function renderLastUpdated(iso) {
  if (!iso) return;
  const d = new Date(iso);
  document.getElementById("last-updated").textContent =
    `Senast uppdaterad: ${d.toLocaleDateString("sv-SE")} ${d.toLocaleTimeString("sv-SE", {hour:"2-digit",minute:"2-digit"})} UTC`;
}

// ── Render: summary cards ──────────────────────────
function renderSummary(data) {
  const grid = document.getElementById("summary-grid");
  const projects = allProjects;
  const selling = projects.filter(p => p.status === "selling");
  const totalAvail = selling.reduce((s, p) => s + (p.available_units || 0), 0);
  const totalSold  = projects.reduce((s, p) => s + (p.sold_units || 0), 0);
  const devCount   = new Set(projects.map(p => p.developer)).size;

  grid.innerHTML = [
    { label: "Totalt projekt",        value: projects.length,                  cls: "" },
    { label: "Aktiva (till salu)",    value: selling.length,                   cls: "green" },
    { label: "Lediga bostäder",       value: fmt(totalAvail),                  cls: "green" },
    { label: "Sålda bostäder",        value: fmt(totalSold),                   cls: "" },
    { label: "Antal utvecklare",      value: devCount,                         cls: "" },
    { label: "Kommande projekt",      value: projects.filter(p=>p.status==="planning").length, cls: "amber" },
  ].map(c => `
    <div class="summary-card ${c.cls}">
      <div class="label">${c.label}</div>
      <div class="value">${c.value}</div>
    </div>`).join("");
}

// ── Render: filters ────────────────────────────────
function populateFilters(projects) {
  const devs = [...new Set(projects.map(p => p.developer))].sort();
  const sel = document.getElementById("filter-developer");
  devs.forEach(d => {
    const opt = document.createElement("option");
    opt.value = d; opt.textContent = d;
    sel.appendChild(opt);
  });
}

function applyFilters() {
  const dev    = document.getElementById("filter-developer").value;
  const status = document.getElementById("filter-status").value;
  const search = document.getElementById("filter-search").value.toLowerCase();

  filteredProjects = allProjects.filter(p => {
    if (dev    && p.developer !== dev)    return false;
    if (status && p.status    !== status) return false;
    if (search && !`${p.name} ${p.location} ${p.municipality}`.toLowerCase().includes(search)) return false;
    return true;
  });

  document.getElementById("project-count").textContent = `${filteredProjects.length} projekt`;
  renderTable(filteredProjects);
}

// ── Render: table ──────────────────────────────────
function renderTable(projects) {
  const sorted = [...projects].sort((a, b) => {
    let va = a[sortCol] ?? "";
    let vb = b[sortCol] ?? "";
    if (typeof va === "number" && typeof vb === "number") {
      return sortDir === "asc" ? va - vb : vb - va;
    }
    va = String(va).toLowerCase();
    vb = String(vb).toLowerCase();
    return sortDir === "asc" ? va.localeCompare(vb, "sv") : vb.localeCompare(va, "sv");
  });

  const tbody = document.getElementById("projects-tbody");
  if (!sorted.length) {
    tbody.innerHTML = `<tr><td colspan="9" class="loading-row">Inga projekt matchar filtret.</td></tr>`;
    return;
  }

  tbody.innerHTML = sorted.map(p => {
    const soldRatio = p.total_units
      ? Math.round(((p.sold_units || 0) / p.total_units) * 100) + "%"
      : "";
    return `
      <tr>
        <td><span class="dev-pill">${esc(p.developer)}</span></td>
        <td><a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.name)}</a></td>
        <td>${esc(p.location || p.municipality || "")}</td>
        <td><span class="badge badge-${p.status || "unknown"}">${STATUS_LABELS[p.status] || p.status}</span></td>
        <td class="num">${p.total_units ?? "—"}</td>
        <td class="num">${p.available_units ?? "—"}</td>
        <td class="num">${p.sold_units ?? "—"}<br><span class="sold-ratio">${soldRatio}</span></td>
        <td class="num">${p.price_from ? fmtSEK(p.price_from) : "—"}</td>
        <td>${p.move_in_date ? fmtDate(p.move_in_date) : "—"}</td>
      </tr>`;
  }).join("");
}

// ── Render: charts ─────────────────────────────────
function renderCharts(projects) {
  // Chart 1: projects per developer
  const devCounts = {};
  projects.forEach(p => { devCounts[p.developer] = (devCounts[p.developer] || 0) + 1; });
  const devLabels = Object.keys(devCounts).sort();
  destroyChart("chart-by-developer");
  charts["chart-by-developer"] = new Chart(document.getElementById("chart-by-developer"), {
    type: "bar",
    data: {
      labels: devLabels,
      datasets: [{
        label: "Projekt",
        data: devLabels.map(d => devCounts[d]),
        backgroundColor: devLabels.map((_, i) => DEVELOPER_COLORS[i % DEVELOPER_COLORS.length]),
        borderRadius: 4,
      }],
    },
    options: chartOptions(""),
  });

  // Chart 2: status distribution (doughnut)
  const statusCounts = {};
  projects.forEach(p => { statusCounts[p.status || "unknown"] = (statusCounts[p.status || "unknown"] || 0) + 1; });
  const statusColors = { selling:"#10b981", planning:"#3b82f6", sold_out:"#ef4444", completed:"#9ca3af", unknown:"#e5e7eb" };
  const statusKeys = Object.keys(statusCounts);
  destroyChart("chart-by-status");
  charts["chart-by-status"] = new Chart(document.getElementById("chart-by-status"), {
    type: "doughnut",
    data: {
      labels: statusKeys.map(k => STATUS_LABELS[k] || k),
      datasets: [{
        data: statusKeys.map(k => statusCounts[k]),
        backgroundColor: statusKeys.map(k => statusColors[k] || "#ccc"),
      }],
    },
    options: { ...chartOptions(""), cutout: "60%", plugins: { legend: { position: "bottom" } } },
  });

  // Chart 3: available units per developer (bar)
  const devAvail = {};
  projects.filter(p => p.status === "selling").forEach(p => {
    devAvail[p.developer] = (devAvail[p.developer] || 0) + (p.available_units || 0);
  });
  const availLabels = Object.keys(devAvail).sort();
  destroyChart("chart-available");
  charts["chart-available"] = new Chart(document.getElementById("chart-available"), {
    type: "bar",
    data: {
      labels: availLabels,
      datasets: [{
        label: "Lediga bostäder",
        data: availLabels.map(d => devAvail[d]),
        backgroundColor: availLabels.map((_, i) => DEVELOPER_COLORS[i % DEVELOPER_COLORS.length]),
        borderRadius: 4,
      }],
    },
    options: chartOptions(""),
  });
}

function chartOptions(title) {
  return {
    responsive: true,
    maintainAspectRatio: true,
    plugins: {
      legend: { display: false },
      title: title ? { display: true, text: title } : undefined,
    },
    scales: {
      x: { grid: { display: false } },
      y: { grid: { color: "#f3f4f6" } },
    },
  };
}

function destroyChart(id) {
  if (charts[id]) { charts[id].destroy(); delete charts[id]; }
}

// ── Render: history ────────────────────────────────
async function renderHistory(index) {
  if (!index || !index.snapshots || index.snapshots.length < 2) return;

  const section = document.getElementById("history-section");
  section.style.display = "";
  section.querySelector(".history-note").style.display = "none";

  // Load last 30 snapshots
  const dates = index.snapshots.slice(0, 30).reverse();
  const snapshots = await Promise.all(
    dates.map(d => fetchJSON(`${HISTORY_BASE}/${d}/all.json`).catch(() => null))
  );

  const developers = [...new Set(allProjects.map(p => p.developer))];
  const datasets = developers.map((dev, i) => ({
    label: dev,
    data: snapshots.map(s => {
      if (!s) return null;
      const devData = (s.developers || {})[dev];
      if (!devData) return null;
      return devData.projects.filter(p => p.status === "selling")
                             .reduce((sum, p) => sum + (p.available_units || 0), 0);
    }),
    borderColor: DEVELOPER_COLORS[i % DEVELOPER_COLORS.length],
    backgroundColor: "transparent",
    tension: 0.3,
    pointRadius: 3,
  }));

  destroyChart("chart-history");
  charts["chart-history"] = new Chart(document.getElementById("chart-history"), {
    type: "line",
    data: { labels: dates, datasets },
    options: {
      responsive: true,
      plugins: { legend: { position: "top" } },
      scales: {
        x: { grid: { display: false } },
        y: { title: { display: true, text: "Lediga bostäder" }, grid: { color: "#f3f4f6" } },
      },
    },
  });
}

// ── Utils ──────────────────────────────────────────
function esc(s) {
  return String(s || "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}
function fmt(n) { return Number(n).toLocaleString("sv-SE"); }
function fmtSEK(n) {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1).replace(".", ",") + " Mkr";
  return fmt(n) + " kr";
}
function fmtDate(s) {
  if (!s) return "—";
  if (s.length === 10) return s.slice(0, 7); // YYYY-MM -> show year-month
  return s.slice(0, 7);
}
function showError(msg) {
  document.getElementById("summary-grid").innerHTML =
    `<div class="summary-card" style="border-color:#dc2626;grid-column:1/-1"><div class="label">Fel</div><p style="margin-top:8px">${msg}</p></div>`;
}

"use strict";

const map = L.map("map", { zoomControl: true }).setView([45.9, 11.3], 8);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "© OpenStreetMap", maxZoom: 18,
}).addTo(map);

const areaLayer = L.layerGroup().addTo(map);   // poligoni coropletici
const flagLayer = L.layerGroup().addTo(map);   // bandierine ai centroidi
const dumpLayer = L.layerGroup();
let mode = "territori";

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function levelForZoom(z) {
  if (z <= 4) return "country";
  if (z <= 6) return "region";
  if (z <= 8) return "province";
  return "comune";
}

function ownerColor(f) {
  return f.is_contested || !f.owner_color ? "#9a8f82" : f.owner_color;
}

function pinIcon(color, label, contested) {
  const bg = contested ? "#9a8f82" : (color || "#6F4E37");
  return L.divIcon({
    className: "",
    html: `<div class="pin" style="background:${bg}"><span>${esc(label)}</span></div>`,
    iconSize: [26, 26], iconAnchor: [13, 26],
  });
}

// ---- Mappa: aree (coropletica + LOD) -------------------------------------
let currentLevel = null;

async function loadAreas(force) {
  const level = levelForZoom(map.getZoom());
  if (!force && level === currentLevel) return;
  currentLevel = level;

  const feats = await fetch("/api/map/areas?level=" + level).then((r) => r.json());
  areaLayer.clearLayers();
  flagLayer.clearLayers();

  if (!feats.length) {              // DB demo (niente geometrie) → marker di ripiego
    if (level === "comune") loadFallbackMarkers();
    return;
  }

  const unit = level === "comune" ? "💩" : "comuni";
  for (const f of feats) {
    const gj = L.geoJSON(
      { type: "Feature", geometry: f.geometry, properties: f },
      {
        style: {
          color: "#fff", weight: 1, fillColor: ownerColor(f),
          fillOpacity: f.owner_id ? 0.55 : 0.25,
        },
      }
    );
    const owner = f.is_contested ? "<i>conteso</i>"
      : (f.owner_name ? `<b>${esc(f.owner_name)}</b>` : "nessuno");
    const link = level === "comune"
      ? `<br><a href="#" onclick="showTerritory(${f.osm_id});return false;">dettaglio →</a>` : "";
    gj.bindPopup(`<b>${esc(f.name)}</b><br>owner: ${owner} (${f.count} ${unit})${link}`);
    areaLayer.addLayer(gj);

    if (f.centroid) {
      const label = f.is_contested ? "?" : (f.owner_name ? f.owner_name[0] : "·");
      flagLayer.addLayer(L.marker(f.centroid, { icon: pinIcon(f.owner_color, label, f.is_contested) }));
    }
  }
}

async function loadFallbackMarkers() {
  const rows = await fetch("/api/map/territories").then((r) => r.json());
  for (const t of rows) {
    const label = t.is_contested ? "?" : (t.owner_name ? t.owner_name[0] : "·");
    const m = L.marker([t.lat, t.lon], { icon: pinIcon(t.owner_color, label, t.is_contested) });
    const owner = t.is_contested ? "<i>conteso</i>"
      : (t.owner_name ? `<b>${esc(t.owner_name)}</b>` : "nessuno");
    m.bindPopup(`<b>${esc(t.name)}</b><br>owner: ${owner} (${t.top_count} 💩)<br>`
      + `<a href="#" onclick="showTerritory(${t.osm_id});return false;">dettaglio →</a>`);
    flagLayer.addLayer(m);
  }
}

map.on("zoomend", () => { if (mode === "territori") loadAreas(false); });

// ---- Mappa: dump (gated) -------------------------------------------------
async function loadDumps() {
  if (!window.LOGGED) return;
  const res = await fetch("/api/map/dumps");
  if (!res.ok) return;
  const rows = await res.json();
  dumpLayer.clearLayers();
  for (const d of rows) {
    const m = L.marker([d.lat, d.lon], {
      icon: L.divIcon({ className: "dump-pin", html: "💩", iconSize: [20, 20] }),
    });
    const selfie = d.has_photo
      ? `<img class="selfie-img" src="/api/selfie/${d.id}" alt="selfie"
             onerror="this.outerHTML='&lt;div class=&quot;selfie&quot;&gt;🐰&lt;/div&gt;'">`
      : `<div class="selfie" title="nessun selfie">🐰</div>`;
    const alt = d.altitude != null ? `${Math.round(d.altitude)} m` : "?";
    m.bindPopup(`${selfie}<div style="margin-top:.4rem"><b>${esc(d.user_name)}</b><br>`
      + `${esc(d.ts)}<br>quota ${alt}</div>`, { maxWidth: 220 });
    dumpLayer.addLayer(m);
  }
}

// ---- Modalità ------------------------------------------------------------
$("#btn-territori").onclick = () => setMode("territori");
$("#btn-dump").onclick = () => setMode("dump");

function setMode(m) {
  const terr = m === "territori";
  if (!terr && !window.LOGGED) {
    alert("I pin dei dump sono visibili solo dopo il login.");
    return;
  }
  mode = m;
  $("#btn-territori").classList.toggle("active", terr);
  $("#btn-dump").classList.toggle("active", !terr);
  if (terr) {
    map.addLayer(areaLayer); map.addLayer(flagLayer); map.removeLayer(dumpLayer);
    loadAreas(true);
  } else {
    map.removeLayer(areaLayer); map.removeLayer(flagLayer); map.addLayer(dumpLayer);
  }
}

// ---- Pannello: tabs ------------------------------------------------------
document.querySelectorAll(".tabs button").forEach((b) => {
  b.onclick = () => {
    document.querySelectorAll(".tabs button").forEach((x) => x.classList.remove("active"));
    document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    $("#tab-" + b.dataset.tab).classList.add("active");
  };
});

async function loadPanels() {
  const lb = await fetch("/api/leaderboard").then((r) => r.json());
  let h = "<table><tr><th>#</th><th>Giocatore</th><th class='num'>comuni</th><th class='num'>km²</th></tr>";
  lb.main.forEach((row, i) => {
    h += `<tr><td>${i + 1}</td><td><span class="swatch" style="background:${esc(row.color || '#6F4E37')}"></span>`
      + `<span class="player-link" onclick="showProfile(${row.user_id})">${esc(row.name)}</span></td>`
      + `<td class="num">${row.comuni}</td><td class="num">${row.km2}</td></tr>`;
  });
  $("#tab-classifica").innerHTML = h + "</table>";

  const labels = {
    nord: "Più a Nord", sud: "Più a Sud", est: "Più a Est", ovest: "Più a Ovest",
    piu_in_alto: "Più in alto", piu_in_basso: "Più in basso", trasferta: "Trasferta",
    esploratore: "Esploratore", volume: "Volume", passaporto: "Passaporto",
    streak: "Streak", latifondista: "Latifondista",
  };
  let r = "";
  for (const [k, lab] of Object.entries(labels)) {
    const rec = lb.records[k];
    const v = rec ? `${esc(rec.name)} <b>${fmtVal(rec.value)}</b>${rec.where ? " @ " + esc(rec.where) : ""}` : "—";
    r += `<div class="rec"><span class="lab">${lab}</span><span>${v}</span></div>`;
  }
  $("#tab-record").innerHTML = r;

  const feed = await fetch("/api/feed").then((r) => r.json());
  $("#tab-feed").innerHTML = feed.map((f) =>
    `<div class="feed-item ${f.kind}"><span class="ts">${esc(f.ts.slice(0, 10))}</span>${esc(f.text)}</div>`
  ).join("");

  // legenda achievement (spiegazione dei badge)
  const badges = await fetch("/api/achievements").then((r) => r.json());
  $("#tab-badge").innerHTML =
    `<p class="hint">Come si sbloccano i badge. Il ? sulla mappa è un territorio <b>conteso</b> (parità): vale zero finché nessuno supera.</p>`
    + badges.map((b) =>
        `<div class="badge-row"><div class="badge-ic">${b.icon || "🏅"}</div>`
        + `<div><b>${esc(b.name)}</b>`
        + `<span class="badge-holders">${b.holders ? "· " + b.holders + " l'hanno preso" : "· nessuno ancora"}</span>`
        + `<div class="badge-desc">${esc(b.description || "")}</div></div></div>`
      ).join("");
}

function fmtVal(v) {
  return (typeof v === "number" && !Number.isInteger(v)) ? v.toFixed(3).replace(/\.?0+$/, "") : v;
}

// ---- Dettaglio territorio -----------------------------------------------
window.showTerritory = async (osm) => {
  const d = await fetch("/api/territory/" + osm).then((r) => r.json());
  const st = d.standings.map((s) => `<tr><td>${esc(s.user)}</td><td class="num">${s.count}</td></tr>`).join("");
  const hist = d.history.map((h) => {
    const nw = h.new || "conteso", p = h.prev ? ` (da ${esc(h.prev)})` : "";
    return `<div class="feed-item"><span class="ts">${esc(h.ts.slice(0, 10))}</span>${esc(nw)}${p}</div>`;
  }).join("");
  $("#detail").innerHTML =
    `<h3>${esc(d.name)}</h3><div class="lab">${esc(d.country || "")} · ${d.area_km2 || "?"} km²</div>`
    + `<table><tr><th>Giocatore</th><th class="num">💩</th></tr>${st}</table>`
    + `<h3 style="margin-top:.6rem">Storia</h3>${hist || "<i>—</i>"}`;
  $("#detail").classList.remove("hidden");
};

// ---- Profilo -------------------------------------------------------------
window.showProfile = async (uid) => {
  const p = await fetch("/api/profile/" + uid).then((r) => r.json());
  const badges = p.badges.map((b) => `${b.icon || "🏅"} ${esc(b.name)}${b.count > 1 ? " ×" + b.count : ""}`).join("<br>");
  const terr = p.territories.map((t) => esc(t.name)).join(", ") || "—";
  $("#modal .modal-box").innerHTML =
    `<span class="close" onclick="closeModal()">×</span>`
    + `<h2><span class="swatch" style="background:${esc(p.color || '#6F4E37')}"></span>${esc(p.name)}</h2>`
    + `<p><b>${p.comuni}</b> comuni · <b>${p.km2}</b> km²</p>`
    + `<h3>Bacheca</h3><p>${badges || "<i>nessun badge</i>"}</p>`
    + `<h3>Territori</h3><p style="font-size:.85rem">${terr}</p>`;
  $("#modal").classList.remove("hidden");
};
window.closeModal = () => $("#modal").classList.add("hidden");
$("#modal").onclick = (e) => { if (e.target.id === "modal") closeModal(); };

// ---- Boot ----------------------------------------------------------------
loadAreas(true);
loadDumps();
loadPanels();

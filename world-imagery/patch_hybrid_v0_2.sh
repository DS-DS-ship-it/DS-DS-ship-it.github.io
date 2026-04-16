#!/usr/bin/env bash
set -euo pipefail

HTML="world-imagery/earth-cockpit-hybrid-v0_1.html"
HYB="world-imagery/hybrid"
LAY="$HYB/layers"

mkdir -p "$LAY"

echo "== Fix Cesium base url typo =="
perl -i.bak -pe 's#window\.CESIUM_BASE_URL\s*=\s*"[^"]*";#window.CESIUM_BASE_URL = "https://unpkg.com/cesium@1.121/Build/Cesium/";#g' "$HTML"

echo "== Ensure ids map2d/globe3d and module path =="
perl -i.bak2 -pe 's/id="view2d"/id="map2d"/g; s/id="view3d"/id="globe3d"/g;' "$HTML"
perl -i.bak3 -pe 's#<script\s+type="module"\s+src="[^"]*"></script>#<script type="module" src="./hybrid/app.js"></script>#g if /type="module"/' "$HTML"

echo "== Write hybrid/state.js =="
cat > "$HYB/state.js" <<'EOF'
export function loadStateFromURL(){
  const p = new URLSearchParams(location.search);
  const mode = p.get("mode");
  const s = {
    mode: (mode === "3d" || mode === "2d") ? mode : "2d",
    layers: {
      radar: (p.get("radar") || "0") === "1",
      quakes:(p.get("quakes")|| "0") === "1",
      fires: (p.get("fires") || "0") === "1",
    },
    debug: (p.get("debug") || "0") === "1",
  };
  return s;
}

export function saveStateToURL(state){
  const p = new URLSearchParams(location.search);
  p.set("mode", state.mode);
  p.set("radar", state.layers.radar ? "1":"0");
  p.set("quakes", state.layers.quakes ? "1":"0");
  p.set("fires", state.layers.fires ? "1":"0");
  p.set("debug", state.debug ? "1":"0");
  const url = `${location.pathname}?${p.toString()}`;
  history.replaceState(null, "", url);
}
EOF

echo "== Write hybrid/ui.js =="
cat > "$HYB/ui.js" <<'EOF'
const $ = (id)=>document.getElementById(id);

export function wireUI(api, state){
  const panel = $("panel");
  const fab = $("fab");

  function setDot(id,on){ const d=$(id); if(!d) return; d.classList.toggle("on", !!on); }

  $("btnMin")?.addEventListener("click", ()=>{
    panel.classList.add("minimized");
    fab.classList.add("show");
  });
  fab?.addEventListener("click", ()=>{
    panel.classList.remove("minimized");
    fab.classList.remove("show");
  });

  $("btn2d")?.addEventListener("click", ()=>api.setMode("2d"));
  $("btn3d")?.addEventListener("click", ()=>api.setMode("3d"));
  $("btnHome")?.addEventListener("click", ()=>api.home());

  $("togRadar")?.addEventListener("click", ()=>api.toggleRadar());
  $("togQuakes")?.addEventListener("click", ()=>api.toggleQuakes());
  $("togFires")?.addEventListener("click", ()=>api.toggleFires());

  $("btnCopy")?.addEventListener("click", ()=>api.copyLink());
  $("btnResetCam")?.addEventListener("click", ()=>api.sync());

  $("togDebug")?.addEventListener("click", ()=>api.toggleDebug());

  // init dots
  setDot("dotRadar", state.layers.radar);
  setDot("dotQuakes", state.layers.quakes);
  setDot("dotFires", state.layers.fires);
  setDot("dotDebug", state.debug);

  // Mobile: auto-minimize so the map is usable
  if (window.matchMedia("(max-width: 720px)").matches) {
    panel.classList.add("minimized");
    fab.classList.add("show");
  }

  return { setDot };
}
EOF

echo "== Write hybrid/layers/base2d.js (Leaflet + upgraded radar + quakes + fires) =="
cat > "$LAY/base2d.js" <<'EOF'
/* 2D Leaflet base + overlays
   Radar upgrade: RainViewer frames API (reduces "gaps" by always choosing latest available frame).
*/
export function make2DMap(el){
  const map = L.map(el, { zoomControl:true, worldCopyJump:true }).setView([28.2, -81.6], 5);

  const esri = L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    { maxZoom: 19, maxNativeZoom: 19, attribution: "Esri World Imagery" }
  ).addTo(map);

  const labels = L.tileLayer(
    "https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
    { maxZoom: 19, maxNativeZoom: 19, attribution: "Esri Reference" }
  ).addTo(map);

  return { map, layers:{ esri, labels } };
}

export async function makeRadarLayer2D(){
  // RainViewer public API: pick newest "radar past" frame (best coverage available at that moment).
  const meta = await fetch("https://api.rainviewer.com/public/weather-maps.json", { cache: "no-store" }).then(r=>r.json());
  const frames = (meta?.radar?.past || []);
  if (!frames.length) throw new Error("RainViewer: no radar frames available");
  const latest = frames[frames.length - 1].path;

  const url = `https://tilecache.rainviewer.com${latest}/256/{z}/{x}/{y}/2/1_1.png`;

  // opacity tuned; you can change later
  return L.tileLayer(url, {
    opacity: 0.70,
    zIndex: 500,
    updateWhenIdle: true,
    updateWhenZooming: false,
    keepBuffer: 6,
    attribution: "RainViewer Radar"
  });
}

export async function makeQuakesLayer2D(){
  const url = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson";
  const gj = await fetch(url, { cache: "no-store" }).then(r=>r.json());
  const layer = L.geoJSON(gj, {
    pointToLayer: (f, latlng) => {
      const mag = (f?.properties?.mag ?? 0);
      const r = Math.max(3, Math.min(16, 3 + mag*2));
      return L.circleMarker(latlng, { radius:r, weight:1, color:"#fff", fillColor:"#ff5b5b", fillOpacity:0.75 });
    },
    onEachFeature: (f, l) => {
      const p = f.properties || {};
      const t = p.title || "Earthquake";
      const when = p.time ? new Date(p.time).toLocaleString() : "";
      l.bindPopup(`<b>${t}</b><br>${when}<br><a href="${p.url}" target="_blank" rel="noreferrer">USGS</a>`);
    }
  });
  return layer;
}

export async function makeFiresLayer2D(){
  // NASA EONET active wildfires (no key)
  const url = "https://eonet.gsfc.nasa.gov/api/v3/events?status=open&category=wildfires&limit=200";
  const data = await fetch(url, { cache: "no-store" }).then(r=>r.json());
  const feats = [];
  for (const e of (data?.events || [])) {
    const geom = e.geometry?.[e.geometry.length - 1];
    if (!geom || geom.type !== "Point") continue;
    const [lon, lat] = geom.coordinates;
    feats.push({
      type:"Feature",
      properties:{ title:e.title, link:e.link, updated:e.geometry?.[e.geometry.length - 1]?.date },
      geometry:{ type:"Point", coordinates:[lon,lat] }
    });
  }

  const layer = L.geoJSON({ type:"FeatureCollection", features:feats }, {
    pointToLayer: (f, latlng) => L.circleMarker(latlng, { radius:6, weight:1, color:"#fff", fillColor:"#ff9f1a", fillOpacity:0.85 }),
    onEachFeature: (f, l) => {
      const p = f.properties || {};
      const when = p.updated ? new Date(p.updated).toLocaleString() : "";
      const link = p.link ? `<a href="${p.link}" target="_blank" rel="noreferrer">details</a>` : "";
      l.bindPopup(`<b>${p.title||"Wildfire"}</b><br>${when}<br>${link}`);
    }
  });
  return layer;
}
EOF

echo "== Write hybrid/layers/base3d.js (Cesium globe stable load + overlays as entities) =="
cat > "$LAY/base3d.js" <<'EOF'
export function make3DGlobe(el){
  if (!window.Cesium) throw new Error("Cesium not loaded");

  // Cesium Ion token not required for our Esri imagery
  const viewer = new Cesium.Viewer(el, {
    animation:false, timeline:false, geocoder:false, homeButton:false,
    baseLayerPicker:false, sceneModePicker:false, navigationHelpButton:false,
    fullscreenButton:false, infoBox:true, selectionIndicator:true,
    imageryProvider: new Cesium.UrlTemplateImageryProvider({
      url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
    })
  });

  // smoother feel
  viewer.scene.globe.depthTestAgainstTerrain = false;
  viewer.scene.screenSpaceCameraController.enableTilt = true;
  viewer.scene.screenSpaceCameraController.enableLook = false;

  return viewer;
}

export function set3DHome(viewer){
  viewer.camera.flyTo({
    destination: Cesium.Cartesian3.fromDegrees(-81.6, 28.2, 2200000.0)
  });
}

export function clear3DEntities(viewer, tag){
  const toRemove = [];
  viewer.entities.values.forEach(e => { if (e?.properties?.tag?.getValue?.() === tag) toRemove.push(e); });
  toRemove.forEach(e => viewer.entities.remove(e));
}

export async function addQuakes3D(viewer){
  const url = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson";
  const gj = await fetch(url, { cache:"no-store" }).then(r=>r.json());
  for (const f of (gj.features || [])) {
    const [lon, lat, dep] = f.geometry?.coordinates || [];
    const mag = (f.properties?.mag ?? 0);
    viewer.entities.add({
      position: Cesium.Cartesian3.fromDegrees(lon, lat, 0),
      point: { pixelSize: Math.max(4, Math.min(16, 4 + mag*2)), color: Cesium.Color.RED.withAlpha(0.85), outlineColor: Cesium.Color.WHITE, outlineWidth: 1 },
      properties: { tag: "quakes" },
      description: `<b>${f.properties?.title || "Earthquake"}</b><br>${f.properties?.time ? new Date(f.properties.time).toLocaleString() : ""}`
    });
  }
}

export async function addFires3D(viewer){
  const url = "https://eonet.gsfc.nasa.gov/api/v3/events?status=open&category=wildfires&limit=200";
  const data = await fetch(url, { cache:"no-store" }).then(r=>r.json());
  for (const e of (data?.events || [])) {
    const geom = e.geometry?.[e.geometry.length - 1];
    if (!geom || geom.type !== "Point") continue;
    const [lon, lat] = geom.coordinates;
    viewer.entities.add({
      position: Cesium.Cartesian3.fromDegrees(lon, lat, 0),
      point: { pixelSize: 10, color: Cesium.Color.ORANGE.withAlpha(0.9), outlineColor: Cesium.Color.WHITE, outlineWidth: 1 },
      properties: { tag: "fires" },
      description: `<b>${e.title}</b><br>${geom.date ? new Date(geom.date).toLocaleString() : ""}<br><a href="${e.link}" target="_blank" rel="noreferrer">details</a>`
    });
  }
}
EOF

echo "== Write hybrid/app.js (glue + debug + mode switching) =="
cat > "$HYB/app.js" <<'EOF'
import { loadStateFromURL, saveStateToURL } from "./state.js";
import { wireUI } from "./ui.js";
import { make2DMap, makeRadarLayer2D, makeQuakesLayer2D, makeFiresLayer2D } from "./layers/base2d.js";
import { make3DGlobe, set3DHome, clear3DEntities, addQuakes3D, addFires3D } from "./layers/base3d.js";

const $ = (id)=>document.getElementById(id);
const dbgEl = $("debug");

const state = loadStateFromURL();

function dbg(...args){
  const s = args.map(a => typeof a === "string" ? a : JSON.stringify(a, null, 2)).join(" ");
  console.log("[HYBRID]", ...args);
  if (dbgEl) dbgEl.textContent += s + "\n";
}

function setDebug(on){
  state.debug = !!on;
  $("dotDebug")?.classList.toggle("on", state.debug);
  if (dbgEl) dbgEl.style.display = state.debug ? "block" : "none";
  saveStateToURL(state);
}

let map2d, map2dLayers;
let radar2d = null, quakes2d = null, fires2d = null;
let viewer3d = null;

const ui = wireUI(api(), state);
setDebug(state.debug);

init().catch(e => { dbg("INIT ERROR:", e?.message || e); });

async function init(){
  // 2D always boots
  ({ map: map2d } = make2DMap("map2d"));
  map2dLayers = map2d;

  // apply initial layer state
  if (state.layers.radar) await enableRadar(true);
  if (state.layers.quakes) await enableQuakes(true);
  if (state.layers.fires) await enableFires(true);

  // mode
  setMode(state.mode);
  dbg("Ready. Mode =", state.mode);
}

function show2D(){
  $("map2d").style.display = "block";
  $("globe3d").style.display = "none";
  map2d.invalidateSize(true);
}
function show3D(){
  $("map2d").style.display = "none";
  $("globe3d").style.display = "block";
  if (!viewer3d) {
    viewer3d = make3DGlobe("globe3d");
    set3DHome(viewer3d);
  }
}

function setMode(m){
  state.mode = (m === "3d") ? "3d" : "2d";
  saveStateToURL(state);
  if (state.mode === "3d") show3D(); else show2D();
}

async function enableRadar(on){
  state.layers.radar = !!on;
  ui.setDot("dotRadar", state.layers.radar);
  saveStateToURL(state);

  if (!state.layers.radar) {
    if (radar2d) { map2d.removeLayer(radar2d); radar2d = null; }
    return;
  }
  try{
    if (!radar2d) radar2d = await makeRadarLayer2D();
    radar2d.addTo(map2d);
    dbg("Radar enabled");
  }catch(e){
    dbg("Radar ERROR:", e?.message || e);
    state.layers.radar = false;
    ui.setDot("dotRadar", false);
    saveStateToURL(state);
  }
}

async function enableQuakes(on){
  state.layers.quakes = !!on;
  ui.setDot("dotQuakes", state.layers.quakes);
  saveStateToURL(state);

  if (!state.layers.quakes) {
    if (quakes2d) { map2d.removeLayer(quakes2d); quakes2d = null; }
    if (viewer3d) clear3DEntities(viewer3d, "quakes");
    return;
  }
  try{
    if (!quakes2d) quakes2d = await makeQuakesLayer2D();
    quakes2d.addTo(map2d);
    if (viewer3d) { clear3DEntities(viewer3d, "quakes"); await addQuakes3D(viewer3d); }
    dbg("Quakes enabled");
  }catch(e){
    dbg("Quakes ERROR:", e?.message || e);
    state.layers.quakes = false;
    ui.setDot("dotQuakes", false);
    saveStateToURL(state);
  }
}

async function enableFires(on){
  state.layers.fires = !!on;
  ui.setDot("dotFires", state.layers.fires);
  saveStateToURL(state);

  if (!state.layers.fires) {
    if (fires2d) { map2d.removeLayer(fires2d); fires2d = null; }
    if (viewer3d) clear3DEntities(viewer3d, "fires");
    return;
  }
  try{
    if (!fires2d) fires2d = await makeFiresLayer2D();
    fires2d.addTo(map2d);
    if (viewer3d) { clear3DEntities(viewer3d, "fires"); await addFires3D(viewer3d); }
    dbg("Fires enabled");
  }catch(e){
    dbg("Fires ERROR:", e?.message || e);
    state.layers.fires = false;
    ui.setDot("dotFires", false);
    saveStateToURL(state);
  }
}

function api(){
  return {
    setMode: (m)=>setMode(m),
    home: ()=>{
      if (state.mode === "2d") map2d.setView([28.2,-81.6], 5);
      else if (viewer3d) set3DHome(viewer3d);
    },
    toggleRadar: ()=>enableRadar(!state.layers.radar),
    toggleQuakes: ()=>enableQuakes(!state.layers.quakes),
    toggleFires: ()=>enableFires(!state.layers.fires),
    sync: ()=>{
      // simple sync: push current 2D center/zoom into 3D camera (approx)
      if (!viewer3d) { dbg("Sync: 3D not initialized yet"); return; }
      const c = map2d.getCenter();
      const z = map2d.getZoom();
      const h = Math.max(1200, 8000000 / Math.pow(2, z)); // rough
      viewer3d.camera.flyTo({ destination: Cesium.Cartesian3.fromDegrees(c.lng, c.lat, h) });
      dbg("Synced 2D → 3D");
    },
    copyLink: async ()=>{
      saveStateToURL(state);
      const url = location.href;
      try{ await navigator.clipboard.writeText(url); dbg("Copied link"); }
      catch{ prompt("Copy link:", url); }
    },
    toggleDebug: ()=>setDebug(!state.debug),
  };
}
EOF

echo "== Done. Files written under world-imagery/hybrid =="
ls -la "$HYB" "$LAY" >/dev/null
echo "Sanity: CESIUM_BASE_URL line:"
grep -n "CESIUM_BASE_URL" "$HTML" || true

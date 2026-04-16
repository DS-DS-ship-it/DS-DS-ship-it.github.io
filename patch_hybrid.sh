#!/usr/bin/env bash
set -euo pipefail

ROOT="$(pwd)"
HTML="world-imagery/earth-cockpit-hybrid-v0_1.html"
HYB="world-imagery/hybrid"
LAY="$HYB/layers"

mkdir -p "$LAY"

echo "== Patch 1/4: Fix Cesium base url typo (cesium@1.121) =="

# 1) Fix the common typo: cesium.121 -> cesium@1.121
perl -i.bak -pe 's#https://unpkg\.com/cesium\.121/#https://unpkg.com/cesium@1.121/#g' "$HTML"

# 2) Ensure CESIUM_BASE_URL is set (and correct) BEFORE Cesium.js loads
perl -0777 -i.bak2 -pe '
my $want = qq{<script>\nwindow.CESIUM_BASE_URL = "https://unpkg.com/cesium@1.121/Build/Cesium/";\n</script>\n};
if ($_ !~ /CESIUM_BASE_URL/) {
  s{(<script\s+src="https://unpkg\.com/cesium\@1\.121/Build/Cesium/Cesium\.js"></script>)}{$want$1}g;
} else {
  s/window\.CESIUM_BASE_URL\s*=\s*\"[^\"]+\";/window.CESIUM_BASE_URL = "https:\\/\\/unpkg.com\\/cesium\\@1.121\\/Build\\/Cesium\\/";/g;
}
' "$HTML"

echo "== Patch 2/4: Write a working Hybrid module set (app/state/ui + 2D/3D layers) =="

cat > "$HYB/state.js" <<'EOF'
export function loadStateFromURL(){
  const p = new URLSearchParams(location.search);
  const state = {
    mode: "2d",
    layers: {
      radar: (p.get("radar") || "0") === "1",
      quakes: (p.get("quakes") || "0") === "1",
      fires: (p.get("fires") || "0") === "1",
    }
  };
  const mode = p.get("mode");
  if (mode === "2d" || mode === "3d") state.mode = mode;
  return state;
}

export function saveStateToURL(state){
  const p = new URLSearchParams(location.search);
  p.set("mode", state.mode);
  p.set("radar", state.layers.radar ? "1" : "0");
  p.set("quakes", state.layers.quakes ? "1" : "0");
  p.set("fires", state.layers.fires ? "1" : "0");
  const url = `${location.pathname}?${p.toString()}`;
  history.replaceState(null, "", url);
  return url;
}
EOF

cat > "$HYB/ui.js" <<'EOF'
const $ = (id) => document.getElementById(id);

export function wireUI(api){
  const setDot = (id, on) => $(id).classList.toggle("on", !!on);
  const dbgBox = $("debug");

  // Buttons
  $("btn2d").addEventListener("click", () => api.setMode("2d"));
  $("btn3d").addEventListener("click", () => api.setMode("3d"));
  $("btnHome").addEventListener("click", api.home);

  $("btnCopy").addEventListener("click", api.copyLink);
  $("btnResetCam").addEventListener("click", api.resetCam);

  // Toggles
  $("togRadar").addEventListener("click", () => api.toggle("radar"));
  $("togQuakes").addEventListener("click", () => api.toggle("quakes"));
  $("togFires").addEventListener("click", () => api.toggle("fires"));

  // Debug
  $("togDebug").addEventListener("click", api.toggleDebug);

  // Panel minimize
  const panel = $("panel") || document.getElementById("panel");
  const fab = $("fab");
  const btnMin = $("btnMin");

  function setMin(min){
    panel.classList.toggle("minimized", !!min);
    fab.classList.toggle("show", !!min);
    btnMin.textContent = min ? "Open" : "Minimize";
  }
  btnMin.addEventListener("click", () => setMin(!panel.classList.contains("minimized")));
  fab.addEventListener("click", () => setMin(false));

  // Let API push UI state
  api._ui = {
    setDot,
    setDebugText: (t) => { if (dbgBox) dbgBox.textContent = t; },
    showDebug: (on) => {
      setDot("dotDebug", on);
      dbgBox.style.display = on ? "block" : "none";
    }
  };

  // Mobile auto-minimize on load
  if (window.matchMedia("(max-width: 720px)").matches) setMin(true);

  return api._ui;
}
EOF

cat > "$LAY/base2d.js" <<'EOF'
const clamp = (v,a,b) => Math.max(a, Math.min(b, v));

export function make2DMap(elId){
  const map = L.map(elId, {
    worldCopyJump: true,
    zoomControl: true,
    preferCanvas: true
  }).setView([20,0], 2);

  const esri = L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    { maxZoom: 19, maxNativeZoom: 19, attribution: "Esri World Imagery" }
  ).addTo(map);

  const labels = L.tileLayer(
    "https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
    { maxZoom: 19, maxNativeZoom: 19, attribution: "Esri Reference" }
  ).addTo(map);

  // ----- Radar (RainViewer) upgraded: use latest timestamp (reduces gaps vs fixed nowcast_0) -----
  let radarLayer = null;
  async function makeRadarLayer(){
    const api = "https://api.rainviewer.com/public/weather-maps.json";
    const r = await fetch(api, { cache: "no-store" });
    const j = await r.json();
    const ts = (j.radar && j.radar.past && j.radar.past.length)
      ? j.radar.past[j.radar.past.length - 1].time
      : null;
    if (!ts) throw new Error("RainViewer: no radar timestamps");
    const url = `https://tilecache.rainviewer.com/v2/radar/${ts}/256/{z}/{x}/{y}/2/1_1.png`;
    return L.tileLayer(url, { opacity: 0.55, maxZoom: 19, maxNativeZoom: 19, attribution: "RainViewer" });
  }

  // ----- Quakes -----
  const quakesGroup = L.layerGroup();
  async function loadQuakes(){
    quakesGroup.clearLayers();
    const url = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson";
    const r = await fetch(url, { cache:"no-store" });
    const j = await r.json();
    for (const f of (j.features || [])){
      const c = f.geometry && f.geometry.coordinates;
      if (!c || c.length < 2) continue;
      const lng = c[0], lat = c[1];
      const mag = f.properties && f.properties.mag != null ? f.properties.mag : 0;
      const rad = clamp(3 + mag * 2.2, 3, 18);
      L.circleMarker([lat,lng], { radius: rad, weight: 1, opacity: 0.9, fillOpacity: 0.35 })
        .bindPopup(`<b>${f.properties?.title || "Earthquake"}</b><br>Mag ${mag}`)
        .addTo(quakesGroup);
    }
  }

  // ----- Fires (GIBS Thermal) -----
  const gibsBase = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best";
  let firesLayer = null;
  function gibsDateUTC(){
    const d = new Date();
    const y = d.getUTCFullYear();
    const m = String(d.getUTCMonth()+1).padStart(2,"0");
    const da = String(d.getUTCDate()).padStart(2,"0");
    return `${y}-${m}-${da}`;
  }
  function makeFiresLayer(){
    const dateStr = gibsDateUTC();
    const url = `${gibsBase}/VIIRS_SNPP_Thermal_Anomalies_375m/default/${dateStr}/GoogleMapsCompatible_Level9/{z}/{y}/{x}.png`;
    return L.tileLayer(url, { opacity: 0.65, maxZoom: 19, maxNativeZoom: 9, attribution: "NASA GIBS (VIIRS Thermal)" });
  }

  return {
    map,
    setRadar: async (on) => {
      if (on){
        if (!radarLayer){
          radarLayer = await makeRadarLayer();
          radarLayer.on("tileerror", () => {});
        }
        radarLayer.addTo(map);
      } else {
        if (radarLayer && map.hasLayer(radarLayer)) map.removeLayer(radarLayer);
      }
    },
    setQuakes: async (on) => {
      if (on){
        await loadQuakes();
        quakesGroup.addTo(map);
      } else {
        if (map.hasLayer(quakesGroup)) map.removeLayer(quakesGroup);
      }
    },
    setFires: (on) => {
      if (on){
        if (!firesLayer) firesLayer = makeFiresLayer();
        firesLayer.addTo(map);
      } else {
        if (firesLayer && map.hasLayer(firesLayer)) map.removeLayer(firesLayer);
      }
    },
    getCenterZoom: () => ({ center: map.getCenter(), zoom: map.getZoom() }),
    setCenterZoom: (lat, lng, zoom) => map.setView([lat,lng], clamp(zoom, 1, 19)),
  };
}
EOF

cat > "$LAY/base3d.js" <<'EOF'
export function make3DGlobe(elId){
  // Ensure Cesium sees its base url for workers/assets
  // (HTML already sets window.CESIUM_BASE_URL)

  const viewer = new Cesium.Viewer(elId, {
    animation: false,
    timeline: false,
    baseLayerPicker: false,
    geocoder: false,
    homeButton: false,
    sceneModePicker: false,
    navigationHelpButton: false,
    fullscreenButton: false,
    infoBox: false,
    selectionIndicator: false,
    shouldAnimate: true,
  });

  // Force a free imagery source (Esri) so we don't rely on Cesium Ion tokens
  viewer.imageryLayers.removeAll();
  viewer.imageryLayers.addImageryProvider(new Cesium.UrlTemplateImageryProvider({
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    maximumLevel: 19
  }));

  // Labels overlay
  viewer.imageryLayers.addImageryProvider(new Cesium.UrlTemplateImageryProvider({
    url: "https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
    maximumLevel: 19
  }));

  viewer.scene.globe.depthTestAgainstTerrain = false;

  // iOS / trackpad feel
  viewer.scene.screenSpaceCameraController.enableTilt = true;

  // Layers
  let radarLayer = null;
  let firesLayer = null;

  // Radar: RainViewer latest timestamp
  async function ensureRadar(){
    if (radarLayer) return;
    const api = "https://api.rainviewer.com/public/weather-maps.json";
    const r = await fetch(api, { cache: "no-store" });
    const j = await r.json();
    const ts = (j.radar && j.radar.past && j.radar.past.length)
      ? j.radar.past[j.radar.past.length - 1].time
      : null;
    if (!ts) throw new Error("RainViewer: no radar timestamps");
    radarLayer = viewer.imageryLayers.addImageryProvider(new Cesium.UrlTemplateImageryProvider({
      url: `https://tilecache.rainviewer.com/v2/radar/${ts}/256/{z}/{x}/{y}/2/1_1.png`,
      maximumLevel: 19
    }));
    radarLayer.alpha = 0.55;
  }

  // Fires: GIBS VIIRS Thermal (Level9)
  function ensureFires(){
    if (firesLayer) return;
    const d = new Date();
    const y = d.getUTCFullYear();
    const m = String(d.getUTCMonth()+1).padStart(2,"0");
    const da = String(d.getUTCDate()).padStart(2,"0");
    const dateStr = `${y}-${m}-${da}`;
    const gibsBase = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best";
    firesLayer = viewer.imageryLayers.addImageryProvider(new Cesium.UrlTemplateImageryProvider({
      url: `${gibsBase}/VIIRS_SNPP_Thermal_Anomalies_375m/default/${dateStr}/GoogleMapsCompatible_Level9/{z}/{y}/{x}.png`,
      maximumLevel: 9
    }));
    firesLayer.alpha = 0.65;
  }

  // Quakes entities
  const quakesDS = new Cesium.CustomDataSource("quakes");
  viewer.dataSources.add(quakesDS);

  async function loadQuakes(){
    quakesDS.entities.removeAll();
    const url = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson";
    const r = await fetch(url, { cache:"no-store" });
    const j = await r.json();
    for (const f of (j.features || [])){
      const c = f.geometry && f.geometry.coordinates;
      if (!c || c.length < 2) continue;
      const lng = c[0], lat = c[1];
      const mag = f.properties && f.properties.mag != null ? f.properties.mag : 0;
      quakesDS.entities.add({
        position: Cesium.Cartesian3.fromDegrees(lng, lat),
        point: {
          pixelSize: Math.min(18, Math.max(6, 6 + mag * 2)),
          color: Cesium.Color.CYAN.withAlpha(0.75),
          outlineColor: Cesium.Color.WHITE.withAlpha(0.6),
          outlineWidth: 1,
          heightReference: Cesium.HeightReference.CLAMP_TO_GROUND
        },
        description: f.properties?.title || "Earthquake"
      });
    }
  }

  function flyHome(){
    viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(0, 20, 25000000.0)
    });
  }
  flyHome();

  return {
    viewer,
    setRadar: async (on) => {
      if (on){
        await ensureRadar();
        radarLayer.show = true;
      } else if (radarLayer) {
        radarLayer.show = false;
      }
    },
    setFires: (on) => {
      if (on){
        ensureFires();
        firesLayer.show = true;
      } else if (firesLayer) {
        firesLayer.show = false;
      }
    },
    setQuakes: async (on) => {
      if (on){
        await loadQuakes();
        quakesDS.show = true;
      } else {
        quakesDS.show = false;
      }
    },
    flyToLatLngZoom: (lat, lng, zoom) => {
      // Convert leaflet-like zoom into a rough height curve
      const z = Math.max(1, Math.min(19, zoom));
      const height = 50000000 / Math.pow(2, z * 0.55);
      viewer.camera.flyTo({ destination: Cesium.Cartesian3.fromDegrees(lng, lat, height) });
    },
    getLatLngZoom: () => {
      const carto = Cesium.Cartographic.fromCartesian(viewer.camera.positionWC);
      const lat = Cesium.Math.toDegrees(carto.latitude);
      const lng = Cesium.Math.toDegrees(carto.longitude);
      const h = carto.height;
      // Rough inverse mapping back to "zoom"
      const zoom = Math.max(1, Math.min(19, Math.round((Math.log(50000000 / Math.max(1,h)) / Math.log(2)) / 0.55)));
      return { lat, lng, zoom };
    },
    home: flyHome
  };
}
EOF

cat > "$HYB/app.js" <<'EOF'
import { loadStateFromURL, saveStateToURL } from "./state.js";
import { wireUI } from "./ui.js";
import { make2DMap } from "./layers/base2d.js";
import { make3DGlobe } from "./layers/base3d.js";

const $ = (id) => document.getElementById(id);

function clampLng(lng){
  // keep [-180, 180]
  return ((lng + 540) % 360) - 180;
}

const state = loadStateFromURL();

const map2d = make2DMap("map2d");
const globe3d = make3DGlobe("globe3d");

let debugOn = false;

function setMode(mode){
  state.mode = mode;
  if (mode === "2d"){
    $("map2d").style.display = "block";
    $("globe3d").style.display = "none";
  } else {
    $("map2d").style.display = "none";
    $("globe3d").style.display = "block";
    globe3d.viewer.resize();
  }
  saveStateToURL(state);
  updateUI();
}

async function applyLayers(){
  await map2d.setRadar(state.layers.radar).catch(()=>{});
  await map2d.setQuakes(state.layers.quakes).catch(()=>{});
  map2d.setFires(state.layers.fires);

  await globe3d.setRadar(state.layers.radar).catch(()=>{});
  await globe3d.setQuakes(state.layers.quakes).catch(()=>{});
  globe3d.setFires(state.layers.fires);
}

function updateUI(){
  if (api._ui){
    api._ui.setDot("dotRadar", state.layers.radar);
    api._ui.setDot("dotQuakes", state.layers.quakes);
    api._ui.setDot("dotFires", state.layers.fires);
    api._ui.showDebug(debugOn);
  }
  updateDebug();
}

function updateDebug(extra=""){
  if (!debugOn || !api._ui) return;

  const c = map2d.getCenterZoom();
  const g = globe3d.getLatLngZoom();
  const txt =
`Mode: ${state.mode}
Layers: radar=${state.layers.radar} quakes=${state.layers.quakes} fires=${state.layers.fires}

2D: center=${c.center.lat.toFixed(5)},${c.center.lng.toFixed(5)} zoom=${c.zoom}
3D: center=${g.lat.toFixed(5)},${g.lng.toFixed(5)} zoom≈${g.zoom}

${extra}`.trim();
  api._ui.setDebugText(txt);
}

function home(){
  map2d.setCenterZoom(20, 0, 2);
  globe3d.home();
  saveStateToURL(state);
  updateUI();
}

function sync2Dto3D(){
  const { center, zoom } = map2d.getCenterZoom();
  globe3d.flyToLatLngZoom(center.lat, clampLng(center.lng), zoom);
  updateDebug("Synced 2D → 3D");
}
function sync3Dto2D(){
  const g = globe3d.getLatLngZoom();
  map2d.setCenterZoom(g.lat, clampLng(g.lng), g.zoom);
  updateDebug("Synced 3D → 2D");
}
function resetCam(){
  if (state.mode === "2d") sync2Dto3D();
  else sync3Dto2D();
}

async function toggle(which){
  state.layers[which] = !state.layers[which];
  saveStateToURL(state);
  await applyLayers();
  updateUI();
}

async function copyLink(){
  const url = saveStateToURL(state);
  try {
    await navigator.clipboard.writeText(location.origin + url);
    updateDebug("Copied link");
  } catch {
    updateDebug("Clipboard blocked by browser");
  }
}

function toggleDebug(){
  debugOn = !debugOn;
  updateUI();
}

const api = { setMode, home, resetCam, toggle, copyLink, toggleDebug, _ui:null };
wireUI(api);

// Keep status updated as you move in 2D
map2d.map.on("moveend zoomend", () => {
  if (state.mode === "2d") updateDebug();
});

// Start
(async () => {
  await applyLayers();
  setMode(state.mode || "2d");
  updateUI();
})();
EOF

echo "== Patch 3/4: Ensure HTML uses map2d/globe3d ids and correct module path =="

# Make sure the HTML contains the required div ids (map2d / globe3d)
perl -i.bak3 -pe 's/id="view2d"/id="map2d"/g; s/id="view3d"/id="globe3d"/g;' "$HTML"

# Ensure module script points to ./hybrid/app.js (relative to world-imagery/)
perl -i.bak4 -pe 's#<script\s+type="module"\s+src="[^"]*hybrid/app\.js"></script>#<script type="module" src="./hybrid/app.js"></script>#g' "$HTML"

echo "== Patch 4/4: Quick sanity output =="
echo "Patched: $HTML"
echo "Created: $HYB/app.js $HYB/state.js $HYB/ui.js $LAY/base2d.js $LAY/base3d.js"


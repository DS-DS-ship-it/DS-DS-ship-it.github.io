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
  setTimeout(()=>map2d.invalidateSize(),100);
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

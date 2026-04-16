/* world-imagery/hybrid/layers/base2d.js
   2D Leaflet base + overlays (Radar, Quakes, Fires)

   Fixes:
   - Radar: RainViewer latest frame + fallback if frame list is empty
   - Quakes: USGS GeoJSON (CORS OK)
   - Fires: NASA GIBS tiles (EONET API is returning 500 for you)
*/

export function make2DMap(el){
  const map = L.map(el, {
    zoomControl: true,
    worldCopyJump: true,
    preferCanvas: true
  }).setView([28.2, -81.6], 5);

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
  const opts = {
    opacity: 0.70,
    zIndex: 500,
    updateWhenIdle: true,
    updateWhenZooming: false,
    keepBuffer: 6,
    attribution: "RainViewer Radar"
  };

  try {
    const meta = await fetch("https://api.rainviewer.com/public/weather-maps.json", { cache: "no-store" }).then(r=>r.json());
    const frames = (meta?.radar?.past || []);
    if (!frames.length) throw new Error("RainViewer: no frames");
    const latest = frames[frames.length - 1].path;
    const url = `https://tilecache.rainviewer.com${latest}/256/{z}/{x}/{y}/2/1_1.png`;
    return L.tileLayer(url, opts);
  } catch (e) {
    // fallback that still shows *something*
    const fallback = "https://tilecache.rainviewer.com/v2/radar/nowcast/256/{z}/{x}/{y}/2/1_1.png";
    return L.tileLayer(fallback, opts);
  }
}

export async function makeQuakesLayer2D(){
  const url = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson";
  const gj = await fetch(url, { cache: "no-store" }).then(r=>r.json());

  return L.geoJSON(gj, {
    pointToLayer: (f, latlng) => {
      const mag = (f?.properties?.mag ?? 0);
      const r = Math.max(3, Math.min(16, 3 + mag*2));
      return L.circleMarker(latlng, { radius:r, weight:1, color:"#fff", fillColor:"#ff5b5b", fillOpacity:0.75 });
    },
    onEachFeature: (f, l) => {
      const p = f.properties || {};
      const t = p.title || "Earthquake";
      const when = p.time ? new Date(p.time).toLocaleString() : "";
      const link = p.url ? `<a href="${p.url}" target="_blank" rel="noreferrer">USGS</a>` : "";
      l.bindPopup(`<b>${t}</b><br>${when}<br>${link}`);
    }
  });
}

export async function makeFiresLayer2D(){
  // EONET is 500 for you, so use NASA GIBS tile layer instead (no key).
  // Pick a stable daily date in UTC.
  const yyyy_mm_dd = new Date().toISOString().slice(0,10);

  // MODIS Terra fire / thermal anomalies:
  const layerName = "MODIS_Terra_Thermal_Anomalies_All";
  const url =
    `https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/${layerName}/default/${yyyy_mm_dd}/GoogleMapsCompatible_Level9/{z}/{y}/{x}.png`;

  return L.tileLayer(url, {
    opacity: 0.75,
    zIndex: 510,
    attribution: "NASA GIBS Fires"
  });
}

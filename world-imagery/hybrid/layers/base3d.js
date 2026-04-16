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

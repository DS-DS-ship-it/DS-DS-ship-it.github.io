#!/usr/bin/env perl
use strict;
use warnings;
use utf8;
use open ':std', ':encoding(UTF-8)';

my $file = shift || 'earth-cockpit-v29.html';

open my $fh, '<', $file or die "Cannot open $file: $!";
local $/;
my $html = <$fh>;
close $fh;

sub replace_exact {
    my ($label, $old, $new) = @_;
    my $count = ($html =~ s/\Q$old\E/$new/s);
    die "Patch failed: $label\n" unless $count;
    print "Patched: $label\n";
}

sub insert_before_exact {
    my ($label, $needle, $insert) = @_;
    my $count = ($html =~ s/\Q$needle\E/$insert$needle/s);
    die "Insert failed: $label\n" unless $count;
    print "Inserted: $label\n";
}

sub insert_after_exact {
    my ($label, $needle, $insert) = @_;
    my $count = ($html =~ s/\Q$needle\E/$needle$insert/s);
    die "Insert failed: $label\n" unless $count;
    print "Inserted: $label\n";
}

# ------------------------------------------------------------------
# 1) Add zoom buttons block above the search box
# ------------------------------------------------------------------
my $search_box = <<'HTML';
      <div class="box">
        <div class="tiny">Search Earth or sky</div>
        <div class="row">
          <input id="searchBox" type="text" placeholder="Orlando, 28.54,-81.38, M31, Vega">
        </div>
        <div class="grid2">
          <button id="searchBtn" class="primary">Go</button>
          <button id="homeBtn">Home</button>
        </div>
      </div>
HTML

my $search_box_new = <<'HTML';
      <div class="box">
        <div class="grid3">
          <button id="zoomInBtn">Zoom +</button>
          <button id="zoomOutBtn">Zoom −</button>
          <button id="homeBtn">Home</button>
        </div>
      </div>

      <div class="box">
        <div class="tiny">Search Earth or sky</div>
        <div class="row">
          <input id="searchBox" type="text" placeholder="Orlando, 28.54,-81.38, M31, Vega">
        </div>
        <div class="grid2">
          <button id="searchBtn" class="primary">Go</button>
          <button id="resetViewBtn">Reset view</button>
        </div>
      </div>
HTML

replace_exact('search box -> zoom/home/reset controls', $search_box, $search_box_new);

# ------------------------------------------------------------------
# 2) Replace goHome() with zoomIn/zoomOut/resetView/goHome
# ------------------------------------------------------------------
my $go_home_old = <<'JS';
  function goHome(){
    if (state.mode === "2d" && state.map2d) {
      state.map2d.setView([CONFIG.home.lat, CONFIG.home.lon], CONFIG.home.zoom2d);
      return;
    }
    if (state.mode === "3d") {
      ensureViewer();
      state.viewer3d.camera.flyTo({
        destination: Cesium.Cartesian3.fromDegrees(CONFIG.home.lon, CONFIG.home.lat, CONFIG.home.height3d),
        duration:1
      });
      return;
    }
    if (state.mode === "astro") {
      $("astroSearchBox").value = "M31";
      astroSearch();
    }
  }
JS

my $go_home_new = <<'JS';
  function zoomIn(){
    if (state.mode === "2d" && state.map2d) {
      state.map2d.zoomIn();
      return;
    }

    if (state.mode === "3d" && state.viewer3d) {
      const cam = state.viewer3d.camera;
      const h = cam.positionCartographic.height;
      cam.zoomIn(Math.max(2500, h * 0.35));
      state.viewer3d.scene.requestRender();
      updateHUD();
      return;
    }

    if (state.mode === "astro") {
      astroZoomIn();
    }
  }

  function zoomOut(){
    if (state.mode === "2d" && state.map2d) {
      state.map2d.zoomOut();
      return;
    }

    if (state.mode === "3d" && state.viewer3d) {
      const cam = state.viewer3d.camera;
      const h = cam.positionCartographic.height;
      cam.zoomOut(Math.max(2500, h * 0.35));
      state.viewer3d.scene.requestRender();
      updateHUD();
      return;
    }

    if (state.mode === "astro") {
      astroZoomOut();
    }
  }

  function goHome(){
    if (state.mode === "2d" && state.map2d) {
      state.map2d.setView([CONFIG.home.lat, CONFIG.home.lon], CONFIG.home.zoom2d);
      return;
    }

    if (state.mode === "3d") {
      ensureViewer();
      state.viewer3d.camera.flyTo({
        destination: Cesium.Cartesian3.fromDegrees(CONFIG.home.lon, CONFIG.home.lat, CONFIG.home.height3d),
        duration: 1.2
      });
      return;
    }

    if (state.mode === "astro") {
      $("astroSearchBox").value = "M31";
      astroSearch();
    }
  }

  function resetView(){
    if (state.mode === "2d" && state.map2d) {
      state.map2d.invalidateSize(true);
      state.map2d.setView([CONFIG.home.lat, CONFIG.home.lon], CONFIG.home.zoom2d);
      return;
    }

    if (state.mode === "3d") {
      ensureViewer();
      state.viewer3d.resize();
      state.viewer3d.camera.flyTo({
        destination: Cesium.Cartesian3.fromDegrees(CONFIG.home.lon, CONFIG.home.lat, CONFIG.home.height3d),
        duration: 0.8
      });
      return;
    }

    if (state.mode === "astro") {
      astroWide();
    }
  }
JS

replace_exact('goHome -> zoomIn/zoomOut/resetView/goHome', $go_home_old, $go_home_new);

# ------------------------------------------------------------------
# 3) Strengthen Cesium camera controls
# ------------------------------------------------------------------
my $viewer_old = <<'JS';
    state.viewer3d = new Cesium.Viewer("map3d", {
      animation:false,
      timeline:false,
      geocoder:false,
      homeButton:false,
      sceneModePicker:false,
      baseLayerPicker:false,
      navigationHelpButton:false,
      infoBox:false,
      selectionIndicator:false,
      terrainProvider:new Cesium.EllipsoidTerrainProvider()
    });
    state.viewer3d.camera.moveEnd.addEventListener(updateHUD);
    setBase3D($("baseSelect").value);
    log("3D initialized");
JS

my $viewer_new = <<'JS';
    state.viewer3d = new Cesium.Viewer("map3d", {
      animation:false,
      timeline:false,
      geocoder:false,
      homeButton:false,
      sceneModePicker:false,
      baseLayerPicker:false,
      navigationHelpButton:false,
      infoBox:false,
      selectionIndicator:false,
      terrainProvider:new Cesium.EllipsoidTerrainProvider(),
      requestRenderMode:true,
      maximumRenderTimeChange:Infinity
    });

    const ssc = state.viewer3d.scene.screenSpaceCameraController;
    ssc.enableZoom = true;
    ssc.enableRotate = true;
    ssc.enableTilt = true;
    ssc.enableTranslate = true;
    ssc.enableLook = true;
    ssc.minimumZoomDistance = 150.0;
    ssc.maximumZoomDistance = 80000000.0;
    ssc.zoomEventTypes = [
      Cesium.CameraEventType.WHEEL,
      Cesium.CameraEventType.PINCH,
      Cesium.CameraEventType.RIGHT_DRAG
    ];

    state.viewer3d.camera.moveEnd.addEventListener(updateHUD);
    setBase3D($("baseSelect").value);
    state.viewer3d.scene.requestRender();
    log("3D initialized");
JS

replace_exact('Cesium camera controls upgrade', $viewer_old, $viewer_new);

# ------------------------------------------------------------------
# 4) Wire the new buttons
# ------------------------------------------------------------------
my $wire_old = <<'JS';
    $("searchBtn").onclick = () => smartSearch();
    $("searchBox").addEventListener("keydown", e => {
      if (e.key === "Enter") smartSearch();
    });
    $("homeBtn").onclick = goHome;
JS

my $wire_new = <<'JS';
    $("searchBtn").onclick = () => smartSearch();
    $("searchBox").addEventListener("keydown", e => {
      if (e.key === "Enter") smartSearch();
    });
    $("zoomInBtn").onclick = zoomIn;
    $("zoomOutBtn").onclick = zoomOut;
    $("homeBtn").onclick = goHome;
    $("resetViewBtn").onclick = resetView;
JS

replace_exact('button wiring for zoom/home/reset', $wire_old, $wire_new);

# ------------------------------------------------------------------
# 5) Add 2D + 3D space-route overlay helpers
# ------------------------------------------------------------------
my $insert_anchor = <<'JS';
  function buildRouteFromWaypoints(waypoints){
JS

my $space_helpers = <<'JS';

  function projectRaDecToLatLon(ra, dec){
    let lon = ((Number(ra) + 180) % 360) - 180;
    let lat = Math.max(-85, Math.min(85, Number(dec)));
    return { lat, lon };
  }

  function clearEarthSpaceRoute(){
    if (state.astro.earthRoute2d && state.map2d) {
      try { state.map2d.removeLayer(state.astro.earthRoute2d); } catch {}
    }
    if (state.astro.earthRoute2dMarkers && state.map2d) {
      try { state.map2d.removeLayer(state.astro.earthRoute2dMarkers); } catch {}
    }
    if (state.astro.earthRoute3d && state.viewer3d) {
      try { state.viewer3d.dataSources.remove(state.astro.earthRoute3d, true); } catch {}
    }
    state.astro.earthRoute2d = null;
    state.astro.earthRoute2dMarkers = null;
    state.astro.earthRoute3d = null;
  }

  function drawEarthSpaceRoute(route){
    clearEarthSpaceRoute();
    if (!route || !route.waypoints || route.waypoints.length < 2) return;

    const ll = route.waypoints.map(wp => {
      const p = projectRaDecToLatLon(wp.ra, wp.dec);
      return [p.lat, p.lon];
    });

    if (state.map2d && ll.length >= 2) {
      state.astro.earthRoute2d = L.polyline(ll, {
        pane: "overlay",
        color: "#7dd3fc",
        weight: 4,
        opacity: 0.9,
        dashArray: "10 8"
      }).addTo(state.map2d);

      const markers = ll.map((pt, i) => L.circleMarker(pt, {
        pane: "overlay",
        radius: i === 0 ? 6 : 5,
        color: i === 0 ? "#22c55e" : "#eab308",
        fillColor: i === 0 ? "#22c55e" : "#eab308",
        fillOpacity: 0.95,
        weight: 2
      }).bindPopup(`${route.waypoints[i].name}<br>RA ${fmt(route.waypoints[i].ra,4)}° • Dec ${fmt(route.waypoints[i].dec,4)}°`));

      state.astro.earthRoute2dMarkers = L.layerGroup(markers).addTo(state.map2d);
    }

    if (state.viewer3d && ll.length >= 2) {
      const ds = new Cesium.CustomDataSource("earthSpaceRoute");
      const positions = ll.map((pt, i) =>
        Cesium.Cartesian3.fromDegrees(
          pt[1],
          pt[0],
          250000.0 + i * 350000.0
        )
      );

      ds.entities.add({
        polyline: {
          positions,
          width: 4,
          material: Cesium.Color.DEEPSKYBLUE.withAlpha(0.95)
        }
      });

      ll.forEach((pt, i) => {
        ds.entities.add({
          position: Cesium.Cartesian3.fromDegrees(pt[1], pt[0], 250000.0 + i * 350000.0),
          point: {
            pixelSize: i === 0 ? 10 : 8,
            color: i === 0 ? Cesium.Color.LIME : Cesium.Color.YELLOW
          },
          label: {
            text: route.waypoints[i].name,
            font: '12px sans-serif',
            fillColor: Cesium.Color.WHITE,
            showBackground: true,
            backgroundColor: Cesium.Color.BLACK.withAlpha(0.55),
            pixelOffset: new Cesium.Cartesian2(0, -18),
            scale: 0.8
          }
        });
      });

      state.viewer3d.dataSources.add(ds);
      state.astro.earthRoute3d = ds;
      state.viewer3d.scene.requestRender();
    }
  }

JS

insert_before_exact('space route helper functions', $insert_anchor, $space_helpers);

# ------------------------------------------------------------------
# 6) Make buildSpaceRoute draw 2D/3D route too
# ------------------------------------------------------------------
my $build_space_old = <<'JS';
  function buildSpaceRoute(){
    const start = getCatalogItemById($("spaceStartSelect").value);
    const end = getCatalogItemById($("spaceEndSelect").value);
    if (!start || !end) return;

    state.astro.waypoints = [structuredClone(start), structuredClone(end)];
    state.astro.route = buildRouteFromWaypoints(state.astro.waypoints);
    drawAstroRoute(state.astro.route);
    log(`Space route built: ${start.name} -> ${end.name}`);
  }
JS

my $build_space_new = <<'JS';
  function buildSpaceRoute(){
    const start = getCatalogItemById($("spaceStartSelect").value);
    const end = getCatalogItemById($("spaceEndSelect").value);
    if (!start || !end) return;

    state.astro.waypoints = [structuredClone(start), structuredClone(end)];
    state.astro.route = buildRouteFromWaypoints(state.astro.waypoints);
    drawAstroRoute(state.astro.route);
    drawEarthSpaceRoute(state.astro.route);
    log(`Space route built: ${start.name} -> ${end.name}`);
  }
JS

replace_exact('buildSpaceRoute draws 2D/3D overlay', $build_space_old, $build_space_new);

# ------------------------------------------------------------------
# 7) Make clearSpaceRoute clear 2D/3D route too
# ------------------------------------------------------------------
my $clear_space_old = <<'JS';
  function clearSpaceRoute(){
    state.astro.waypoints = [];
    state.astro.route = null;
    clearAstroRouteGraphics();
    renderWaypointList();
    updateSpaceOutputs(null);
    log("Space route cleared");
  }
JS

my $clear_space_new = <<'JS';
  function clearSpaceRoute(){
    state.astro.waypoints = [];
    state.astro.route = null;
    clearAstroRouteGraphics();
    clearEarthSpaceRoute();
    renderWaypointList();
    updateSpaceOutputs(null);
    log("Space route cleared");
  }
JS

replace_exact('clearSpaceRoute clears 2D/3D overlay', $clear_space_old, $clear_space_new);

# ------------------------------------------------------------------
# 8) Add astro route handles into state.astro
# ------------------------------------------------------------------
my $astro_state_old = <<'JS';
    astro: {
      instance: null,
      survey: "P/DSS2/color",
      target: "M31",
      fov: 120,
      reticle: true,
      catalogLayer: null,
      routeCatalog: null,
      overlay: null,
      route: null,
      waypoints: [],
      currentCatalogFilter: "all",
      cursorRa: null,
      cursorDec: null
    },
JS

my $astro_state_new = <<'JS';
    astro: {
      instance: null,
      survey: "P/DSS2/color",
      target: "M31",
      fov: 120,
      reticle: true,
      catalogLayer: null,
      routeCatalog: null,
      overlay: null,
      route: null,
      waypoints: [],
      currentCatalogFilter: "all",
      cursorRa: null,
      cursorDec: null,
      earthRoute2d: null,
      earthRoute2dMarkers: null,
      earthRoute3d: null
    },
JS

replace_exact('state.astro route handles', $astro_state_old, $astro_state_new);

# ------------------------------------------------------------------
# 9) Backup and write
# ------------------------------------------------------------------
my $bak = $file . '.bak';
open my $b, '>', $bak or die "Cannot write $bak: $!";
print {$b} $html;
close $b;

open my $out, '>', $file or die "Cannot write $file: $!";
print {$out} $html;
close $out;

print "\nDone.\n";
print "Patched file: $file\n";
print "Backup copy : $bak\n";

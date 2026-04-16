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

sub backup_file {
    my ($path, $content) = @_;
    my $bak = $path . '.bak_v2';
    open my $out, '>', $bak or die "Cannot write backup $bak: $!";
    print {$out} $content;
    close $out;
    print "Backup written: $bak\n";
}

sub find_anchor {
    my (@choices) = @_;
    for my $c (@choices) {
        my $pos = index($html, $c);
        return ($c, $pos) if $pos >= 0;
    }
    return;
}

sub insert_before_first_found {
    my ($label, $insert, @anchors) = @_;
    my ($anchor, $pos) = find_anchor(@anchors);
    die "Patch failed: $label (no anchor found)\n" unless defined $anchor;
    substr($html, $pos, 0, $insert);
    print "Inserted: $label\n";
}

sub insert_after_first_found {
    my ($label, $insert, @anchors) = @_;
    my ($anchor, $pos) = find_anchor(@anchors);
    die "Patch failed: $label (no anchor found)\n" unless defined $anchor;
    $pos += length($anchor);
    substr($html, $pos, 0, $insert);
    print "Inserted: $label\n";
}

sub replace_exact_once {
    my ($label, $old, $new) = @_;
    my $pos = index($html, $old);
    die "Patch failed: $label (exact block not found)\n" if $pos < 0;
    substr($html, $pos, length($old), $new);
    print "Patched: $label\n";
}

backup_file($file, $html);

# ---------------------------------------------------------
# 1) Restore missing top controls
# ---------------------------------------------------------
if (index($html, 'id="zoomInBtn"') < 0) {
    my $block = <<'HTML';

      <div class="box">
        <div class="grid3">
          <button id="zoomInBtn">Zoom +</button>
          <button id="zoomOutBtn">Zoom −</button>
          <button id="resetBtn">Reset</button>
        </div>
        <div class="grid3" style="margin-top:6px;">
          <button id="refreshBtn">Refresh</button>
          <button id="healthBtn">Health</button>
          <button id="copyLogBtn">Copy log</button>
        </div>
      </div>
HTML
    insert_after_first_found(
        'restore zoom/reset controls',
        $block,
        '<span id="statusBadge" class="badge warn">Booting</span>',
        '<span id="statusBadge" class="badge ok">Ready</span>'
    );
}

if (index($html, 'id="searchBtn"') < 0) {
    my $block = <<'HTML';

      <div class="box">
        <div class="tiny">Search Earth or sky</div>
        <div class="row">
          <input id="searchBox" type="text" placeholder="Orlando, 28.54,-81.38, M31, Vega, NGC 1300">
        </div>
        <div class="grid2">
          <button id="searchBtn" class="primary">Go</button>
          <button id="homeBtn">Home</button>
        </div>
      </div>
HTML
    insert_before_first_found(
        'restore search box',
        $block,
        '<div class="tiny"><b>Base layer</b></div>',
        '<div class="box">
        <div class="tiny"><b>Base layer</b></div>'
    );
}

# ---------------------------------------------------------
# 2) Restore missing mid-panel feature boxes before diagnostics
# ---------------------------------------------------------
my $weather_block = <<'HTML';
      <div class="box">
        <div class="tiny"><b>Weather</b></div>
        <label class="check"><input id="radarChk" type="checkbox"> Radar / precipitation animation</label>
        <label class="check"><input id="cloudsChk" type="checkbox"> NASA GIBS clouds</label>
        <label class="check"><input id="precipChk" type="checkbox"> NASA GIBS precipitation</label>
        <label class="check"><input id="thermalChk" type="checkbox"> NASA GIBS thermal anomalies</label>
        <label class="check"><input id="windHeatChk" type="checkbox"> Wind heat endpoint</label>
        <label class="check"><input id="hurricaneChk" type="checkbox"> Hurricane tracks endpoint</label>

        <div class="grid3">
          <button id="radarAnimateBtn">Animate</button>
          <button id="radarStepBtn">Step</button>
          <button id="radarReloadBtn">Reload</button>
        </div>

        <div class="row" style="margin-top:6px;">
          <select id="radarTrailSelect">
            <option value="0">Radar trail off</option>
            <option value="2">2 trail frames</option>
            <option value="4" selected>4 trail frames</option>
            <option value="6">6 trail frames</option>
          </select>
        </div>

        <div id="radarStamp" class="tiny" style="margin-top:6px;">off</div>
      </div>

HTML

my $mobility_block = <<'HTML';
      <div class="box">
        <div class="tiny"><b>Mobility / traffic / travel</b></div>
        <label class="check"><input id="trafficSpeedChk" type="checkbox"> Traffic roads overlay</label>
        <label class="check"><input id="trafficIncidentsChk" type="checkbox"> Traffic incidents endpoint</label>
        <label class="check"><input id="constructionChk" type="checkbox"> Construction overlay</label>
        <label class="check"><input id="vehicleHeatChk" type="checkbox"> Vehicle density heatmap endpoint</label>
        <label class="check"><input id="aircraftChk" type="checkbox"> ADS-B aircraft</label>
        <label class="check"><input id="shipsChk" type="checkbox"> AIS ships endpoint</label>
        <label class="check"><input id="airspaceChk" type="checkbox"> Restricted airspace endpoint</label>

        <div class="tiny" style="margin-top:8px;">
          If no traffic-speed or construction endpoint is provided, the code falls back to live OSM road/construction geometry for the current viewport.
        </div>
      </div>

HTML

my $drive_block = <<'HTML';
      <div class="box">
        <div class="tiny"><b>Drive / navigation</b></div>

        <div class="tiny" style="margin-top:6px;">Start</div>
        <input id="driveStartInput" type="text" placeholder="current location, Orlando, or 28.5383,-81.3792">

        <div class="tiny" style="margin-top:6px;">End</div>
        <input id="driveEndInput" type="text" placeholder="destination address or lat,lon">

        <div class="grid2" style="margin-top:6px;">
          <select id="driveModeSelect">
            <option value="fastest">Fastest</option>
            <option value="safest">Safest</option>
            <option value="avoid_tolls">Avoid tolls</option>
          </select>
          <select id="driveCorridorSelect">
            <option value="25">City corridor 25 m</option>
            <option value="35" selected>Balanced corridor 35 m</option>
            <option value="60">Highway corridor 60 m</option>
            <option value="90">Wide corridor 90 m</option>
          </select>
        </div>

        <div class="grid2" style="margin-top:6px;">
          <button id="driveRouteBtn" class="primary">Start route</button>
          <button id="driveClearBtn">Clear route</button>
        </div>

        <div class="grid2" style="margin-top:6px;">
          <button id="driveUseHereBtn">Use my location</button>
          <button id="driveSwapBtn">Swap</button>
        </div>

        <label class="check" style="margin-top:8px;"><input id="driveAutoRerouteChk" type="checkbox" checked> Auto-reroute</label>
        <label class="check"><input id="driveSpeedLimitChk" type="checkbox" checked> Speed-limit lookup</label>
        <label class="check"><input id="driveOverspeedChk" type="checkbox" checked> Overspeed alerts</label>
        <label class="check"><input id="driveStreetFollowChk" type="checkbox"> Street-view follow</label>
        <label class="check"><input id="driveWatchGpsChk" type="checkbox" checked> Watch live GPS</label>

        <div class="tiny" style="margin-top:8px;">Overspeed margin</div>
        <div class="row">
          <input id="driveOverspeedMargin" type="range" min="0" max="20" value="5">
        </div>
        <div id="driveOverspeedMarginOut" class="tiny">5 mph</div>

        <div class="sep"></div>

        <div class="kv"><div class="tiny">Distance left</div><div id="driveDistanceOut" class="tinyout">—</div></div>
        <div class="kv"><div class="tiny">ETA</div><div id="driveEtaOut" class="tinyout">—</div></div>
        <div class="kv"><div class="tiny">Next turn</div><div id="driveNextOut" class="tinyout">—</div></div>
        <div class="kv"><div class="tiny">Road</div><div id="driveRoadOut" class="tinyout">—</div></div>
        <div class="kv"><div class="tiny">Speed limit</div><div id="driveSpeedLimitOut" class="tinyout">—</div></div>
        <div class="kv"><div class="tiny">Current speed</div><div id="driveCurrentSpeedOut" class="tinyout">—</div></div>
      </div>

HTML

my $hazards_block = <<'HTML';
      <div class="box">
        <div class="tiny"><b>Hazards</b></div>
        <label class="check"><input id="firesChk" type="checkbox"> Wildfires (NASA EONET)</label>
        <label class="check"><input id="quakesChk" type="checkbox"> USGS earthquakes</label>
        <label class="check"><input id="sentinelFootprintsChk" type="checkbox"> Sentinel-2 footprints</label>
        <label class="check"><input id="sentinelOverlayChk" type="checkbox"> Sentinel imagery overlay</label>
        <label class="check"><input id="satellitesChk" type="checkbox"> Real-time satellites</label>
      </div>

      <div class="box">
        <div class="tiny"><b>Overlay opacity</b></div>
        <div class="row">
          <input id="overlayOpacity" type="range" min="0" max="100" value="72">
        </div>
      </div>

HTML

if (index($html, 'id="radarChk"') < 0) {
    insert_before_first_found(
        'restore weather box',
        $weather_block,
        '<div class="tiny"><b>Diagnostics</b></div>',
        '<div id="log" class="mono tiny"'
    );
}

if (index($html, 'id="trafficSpeedChk"') < 0) {
    insert_before_first_found(
        'restore mobility box',
        $mobility_block,
        '<div class="tiny"><b>Diagnostics</b></div>',
        '<div id="log" class="mono tiny"'
    );
}

if (index($html, 'id="driveRouteBtn"') < 0) {
    insert_before_first_found(
        'restore drive box',
        $drive_block,
        '<div class="tiny"><b>Diagnostics</b></div>',
        '<div id="log" class="mono tiny"'
    );
}

if (index($html, 'id="firesChk"') < 0) {
    insert_before_first_found(
        'restore hazards/opacity boxes',
        $hazards_block,
        '<div class="tiny"><b>Diagnostics</b></div>',
        '<div id="log" class="mono tiny"'
    );
}

# ---------------------------------------------------------
# 3) Restore street panel
# ---------------------------------------------------------
if (index($html, 'id="streetPanel"') < 0) {
    my $street = <<'HTML';

      <div id="streetPanel">
        <div id="streetPanelHeader">
          <span id="streetPanelTitle">Street view idle</span>
          <div style="display:flex;gap:6px;">
            <button id="streetRefreshBtn">Refresh</button>
            <button id="streetHideBtn">Hide</button>
          </div>
        </div>
        <iframe id="streetFrame" referrerpolicy="no-referrer-when-downgrade" allowfullscreen></iframe>
      </div>
HTML
    insert_before_first_found('restore street panel', $street, '</main>');
}

# ---------------------------------------------------------
# 4) Add stronger 3D zoom helpers if missing
# ---------------------------------------------------------
if (index($html, 'function zoomIn(){') < 0) {
    my $insert = <<'JS';

  function zoomIn(){
    if (state.mode === "2d" && state.map2d) {
      state.map2d.zoomIn();
      return;
    }
    if (state.mode === "3d" && state.viewer3d) {
      const cam = state.viewer3d.camera;
      const h = cam.positionCartographic.height || 10000000;
      cam.zoomIn(Math.max(5000, h * 0.35));
      state.viewer3d.scene.requestRender();
      updateHUD();
      return;
    }
    if (state.mode === "astro") {
      astroZoomIn();
      return;
    }
  }

  function zoomOut(){
    if (state.mode === "2d" && state.map2d) {
      state.map2d.zoomOut();
      return;
    }
    if (state.mode === "3d" && state.viewer3d) {
      const cam = state.viewer3d.camera;
      const h = cam.positionCartographic.height || 10000000;
      cam.zoomOut(Math.max(5000, h * 0.35));
      state.viewer3d.scene.requestRender();
      updateHUD();
      return;
    }
    if (state.mode === "astro") {
      astroZoomOut();
      return;
    }
  }

  function resetView(){
    if (state.mode === "2d" && state.map2d) {
      state.map2d.invalidateSize(true);
      state.map2d.setView([CONFIG.home.lat, CONFIG.home.lon], CONFIG.home.zoom2d);
      return;
    }
    if (state.mode === "3d" && state.viewer3d) {
      ensureViewer();
      state.viewer3d.resize();
      state.viewer3d.camera.flyTo({
        destination: Cesium.Cartesian3.fromDegrees(CONFIG.home.lon, CONFIG.home.lat, CONFIG.home.height3d),
        duration: 0.9
      });
      return;
    }
    if (state.mode === "astro") {
      astroWide();
      return;
    }
  }

JS
    insert_before_first_found('add zoom/reset functions', $insert, '  function goHome(){', 'function goHome(){');
}

# ---------------------------------------------------------
# 5) Add projected Astro route into 2D and 3D if missing
# ---------------------------------------------------------
if (index($html, 'function drawEarthSpaceRoute(') < 0) {
    my $insert = <<'JS';

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

      const markers = ll.map((pt, i) =>
        L.circleMarker(pt, {
          pane: "overlay",
          radius: i === 0 ? 7 : 6,
          color: i === 0 ? "#22c55e" : "#eab308",
          fillColor: i === 0 ? "#22c55e" : "#eab308",
          fillOpacity: 0.95,
          weight: 2
        }).bindPopup(`${route.waypoints[i].name}<br>RA ${fmt(route.waypoints[i].ra,4)}° • Dec ${fmt(route.waypoints[i].dec,4)}°`)
      );

      state.astro.earthRoute2dMarkers = L.layerGroup(markers).addTo(state.map2d);
    }

    if (state.viewer3d && ll.length >= 2) {
      const ds = new Cesium.CustomDataSource("earthSpaceRoute");
      const positions = ll.map((pt, i) =>
        Cesium.Cartesian3.fromDegrees(pt[1], pt[0], 250000.0 + i * 300000.0)
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
          position: Cesium.Cartesian3.fromDegrees(pt[1], pt[0], 250000.0 + i * 300000.0),
          point: {
            pixelSize: i === 0 ? 10 : 8,
            color: i === 0 ? Cesium.Color.LIME : Cesium.Color.YELLOW
          }
        });
      });

      state.viewer3d.dataSources.add(ds);
      state.astro.earthRoute3d = ds;
      state.viewer3d.scene.requestRender();
    }
  }

JS
    insert_before_first_found(
        'add projected earth-space route helpers',
        $insert,
        '  function buildRouteFromWaypoints(waypoints){',
        'function buildRouteFromWaypoints(waypoints){'
    );
}

if (index($html, 'drawEarthSpaceRoute(state.astro.route);') < 0) {
    my $old = <<'JS';
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

    my $new = <<'JS';
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
    replace_exact_once('buildSpaceRoute also draws 2D/3D route', $old, $new);
}

if (index($html, 'clearEarthSpaceRoute();') < 0) {
    my $old = <<'JS';
  function clearSpaceRoute(){
    state.astro.waypoints = [];
    state.astro.route = null;
    clearAstroRouteGraphics();
    renderWaypointList();
    updateSpaceOutputs(null);
    log("Space route cleared");
  }
JS

    my $new = <<'JS';
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
    replace_exact_once('clearSpaceRoute also clears 2D/3D route', $old, $new);
}

# ---------------------------------------------------------
# 6) Add missing state handles for projected route
# ---------------------------------------------------------
if (index($html, 'earthRoute2d') < 0) {
    my $old = <<'JS';
      currentCatalogFilter: "all",
      cursorRa: null,
      cursorDec: null
    },
JS
    my $new = <<'JS';
      currentCatalogFilter: "all",
      cursorRa: null,
      cursorDec: null,
      earthRoute2d: null,
      earthRoute2dMarkers: null,
      earthRoute3d: null
    },
JS
    replace_exact_once('add astro projected-route state', $old, $new);
}

# ---------------------------------------------------------
# 7) Fallback wiring for buttons
# ---------------------------------------------------------
if (index($html, 'function wireMissingUiFallbacks(){') < 0) {
    my $insert = <<'JS';

  function wireMissingUiFallbacks(){
    const on = (id, fn) => {
      const el = $(id);
      if (el) el.onclick = fn;
    };

    on("zoomInBtn", zoomIn);
    on("zoomOutBtn", zoomOut);
    on("resetBtn", resetView);
    on("homeBtn", goHome);

    on("mode2d", () => showMode("2d"));
    on("mode3d", () => showMode("3d"));
    on("modeAstro", () => showMode("astro"));

    if ($("searchBtn") && $("searchBox")) {
      $("searchBtn").onclick = () => smartSearch().catch(e => log(`Search failed: ${e.message}`));
      $("searchBox").addEventListener("keydown", e => {
        if (e.key === "Enter") smartSearch().catch(err => log(`Search failed: ${err.message}`));
      });
    }

    on("spaceBuildBtn", buildSpaceRoute);
    on("spaceClearBtn", clearSpaceRoute);
  }

JS
    insert_before_first_found('add fallback button wiring', $insert, '  async function boot(){', 'async function boot(){');
}

if (index($html, 'wireMissingUiFallbacks();') < 0) {
    my $old = "    fillSpaceSelectors();\n";
    my $new = "    fillSpaceSelectors();\n    wireMissingUiFallbacks();\n";
    replace_exact_once('boot calls fallback button wiring', $old, $new);
}

# ---------------------------------------------------------
# 8) Write back
# ---------------------------------------------------------
open my $out, '>', $file or die "Cannot write $file: $!";
print {$out} $html;
close $out;

print "\nDone.\n";
print "Patched file: $file\n";

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
    my $bak = $path . '.bak_space_v3';
    open my $out, '>', $bak or die "Cannot write backup $bak: $!";
    print {$out} $content;
    close $out;
    print "Backup written: $bak\n";
}

sub insert_before_first_found {
    my ($label, $insert, @anchors) = @_;
    for my $anchor (@anchors) {
        my $pos = index($html, $anchor);
        if ($pos >= 0) {
            substr($html, $pos, 0, $insert);
            print "Inserted: $label\n";
            return 1;
        }
    }
    die "Patch failed: $label (no anchor found)\n";
}

sub replace_exact_once {
    my ($label, $old, $new) = @_;
    my $pos = index($html, $old);
    die "Patch failed: $label (exact block not found)\n" if $pos < 0;
    substr($html, $pos, length($old), $new);
    print "Patched: $label\n";
}

backup_file($file, $html);

# 1) Add missing astro state holders if not present
if (index($html, 'earthRoute2d') < 0) {
    my $old = <<'OLD';
      currentCatalogFilter: "all",
      cursorRa: null,
      cursorDec: null
    },
OLD

    my $new = <<'NEW';
      currentCatalogFilter: "all",
      cursorRa: null,
      cursorDec: null,
      earthRoute2d: null,
      earthRoute2dMarkers: null,
      earthRoute3d: null
    },
NEW

    replace_exact_once('add astro projected-route state', $old, $new);
}

# 2) Add projected 2D/3D space-route helpers
if (index($html, 'function drawEarthSpaceRoute(') < 0) {
    my $insert = <<'JS';

  function projectRaDecToLatLon(ra, dec){
    let lon = ((((Number(ra) || 0) + 180) % 360) + 360) % 360 - 180;
    let lat = Math.max(-85, Math.min(85, Number(dec) || 0));
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
        opacity: 0.92,
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
        }).bindPopup(
          `${route.waypoints[i].name}<br>RA ${fmt(route.waypoints[i].ra,4)}° • Dec ${fmt(route.waypoints[i].dec,4)}°`
        )
      );

      state.astro.earthRoute2dMarkers = L.layerGroup(markers).addTo(state.map2d);
    }

    if (state.viewer3d && ll.length >= 2) {
      const ds = new Cesium.CustomDataSource("earthSpaceRoute");
      const positions = ll.map((pt, i) =>
        Cesium.Cartesian3.fromDegrees(pt[1], pt[0], 300000 + i * 250000)
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
          position: Cesium.Cartesian3.fromDegrees(pt[1], pt[0], 300000 + i * 250000),
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
        '  function buildSpaceRoute(){',
        'function buildSpaceRoute(){',
        '  function clearSpaceRoute(){',
        'function clearSpaceRoute(){',
        '  async function boot(){',
        'async function boot(){'
    );
}

# 3) Make buildSpaceRoute also draw 2D/3D projected route
if (index($html, 'drawEarthSpaceRoute(state.astro.route);') < 0) {
    my $old = <<'OLD';
  function buildSpaceRoute(){
    const start = getCatalogItemById($("spaceStartSelect").value);
    const end = getCatalogItemById($("spaceEndSelect").value);
    if (!start || !end) return;

    state.astro.waypoints = [structuredClone(start), structuredClone(end)];
    state.astro.route = buildRouteFromWaypoints(state.astro.waypoints);
    drawAstroRoute(state.astro.route);
    log(`Space route built: ${start.name} -> ${end.name}`);
  }
OLD

    my $new = <<'NEW';
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
NEW

    replace_exact_once('buildSpaceRoute draws 2D/3D route', $old, $new);
}

# 4) Make clearSpaceRoute also remove 2D/3D projected route
if (index($html, 'clearEarthSpaceRoute();') < 0) {
    my $old = <<'OLD';
  function clearSpaceRoute(){
    state.astro.waypoints = [];
    state.astro.route = null;
    clearAstroRouteGraphics();
    renderWaypointList();
    updateSpaceOutputs(null);
    log("Space route cleared");
  }
OLD

    my $new = <<'NEW';
  function clearSpaceRoute(){
    state.astro.waypoints = [];
    state.astro.route = null;
    clearAstroRouteGraphics();
    clearEarthSpaceRoute();
    renderWaypointList();
    updateSpaceOutputs(null);
    log("Space route cleared");
  }
NEW

    replace_exact_once('clearSpaceRoute clears 2D/3D route', $old, $new);
}

open my $out, '>', $file or die "Cannot write $file: $!";
print {$out} $html;
close $out;

print "\nDone.\nPatched file: $file\n";

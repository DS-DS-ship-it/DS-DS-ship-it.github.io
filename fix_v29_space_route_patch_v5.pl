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
    my $bak = $path . '.bak_space_v5';
    open my $out, '>', $bak or die "Cannot write backup $bak: $!";
    print {$out} $content;
    close $out;
    print "Backup written: $bak\n";
}

sub replace_function_block {
    my ($name, $replacement) = @_;
    my $pattern = qr/function \Q$name\E\(\)\s*\{.*?\n\}(?=\n\s*function |\n\s*async function |\n\s*const |\n\s*let |\n\s*var |\n\s*\/\/|\n\s*$)/s;
    my $count = ($html =~ s/$pattern/$replacement/s);
    die "Patch failed: replace function $name\n" unless $count;
    print "Patched: replace function $name\n";
}

sub insert_before_anchor {
    my ($label, $insert, @anchors) = @_;
    for my $anchor (@anchors) {
        my $pos = index($html, $anchor);
        next if $pos < 0;
        substr($html, $pos, 0, $insert);
        print "Inserted: $label\n";
        return 1;
    }
    die "Patch failed: $label\n";
}

backup_file($file, $html);

# 1) Add missing astro projected-route state if needed
if (index($html, 'earthRoute2d') < 0) {
    my $done = 0;

    if ($html =~ /(astro:\s*\{\s*\n)/s) {
        $html =~ s/(astro:\s*\{\s*\n)/$1      earthRoute2d: null,\n      earthRoute2dMarkers: null,\n      earthRoute3d: null,\n/s;
        print "Patched: add astro route state\n";
        $done = 1;
    }

    die "Patch failed: add astro route state\n" unless $done;
}

# 2) Inject helpers if missing
if (index($html, 'function drawEarthSpaceRoute(') < 0) {
    my $helpers = <<'JS';

  function projectRaDecToLatLon(ra, dec){
    const lon = ((((Number(ra) || 0) + 180) % 360) + 360) % 360 - 180;
    const lat = Math.max(-85, Math.min(85, Number(dec) || 0));
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

    const latlngs = route.waypoints.map(wp => {
      const p = projectRaDecToLatLon(wp.ra, wp.dec);
      return [p.lat, p.lon];
    });

    if (state.map2d && latlngs.length >= 2) {
      state.astro.earthRoute2d = L.polyline(latlngs, {
        pane: "overlay",
        color: "#7dd3fc",
        weight: 4,
        opacity: 0.95,
        dashArray: "10 8"
      }).addTo(state.map2d);

      const markers = latlngs.map((pt, i) => {
        const wp = route.waypoints[i];
        return L.circleMarker(pt, {
          pane: "overlay",
          radius: i === 0 ? 7 : 6,
          color: i === 0 ? "#22c55e" : "#eab308",
          fillColor: i === 0 ? "#22c55e" : "#eab308",
          fillOpacity: 0.95,
          weight: 2
        }).bindPopup(
          `<b>${wp.name}</b><br>RA ${fmt(wp.ra,4)}° • Dec ${fmt(wp.dec,4)}°<br>${formatSpaceDistance(wp.distanceLy)}`
        );
      });

      state.astro.earthRoute2dMarkers = L.layerGroup(markers).addTo(state.map2d);

      try {
        const bounds = L.latLngBounds(latlngs);
        if (bounds.isValid()) state.map2d.fitBounds(bounds.pad(0.2));
      } catch {}
    }

    if (state.viewer3d && latlngs.length >= 2) {
      const ds = new Cesium.CustomDataSource("earthSpaceRoute");
      const positions = latlngs.map((pt, i) =>
        Cesium.Cartesian3.fromDegrees(pt[1], pt[0], 300000 + i * 250000)
      );

      ds.entities.add({
        polyline: {
          positions,
          width: 4,
          material: Cesium.Color.DEEPSKYBLUE.withAlpha(0.95)
        }
      });

      latlngs.forEach((pt, i) => {
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

      try {
        state.viewer3d.flyTo(ds, { duration: 1.6 });
      } catch {}
      state.viewer3d.scene.requestRender();
    }
  }

JS

    insert_before_anchor(
        'earth-space route helpers',
        $helpers,
        'function clearSpaceRoute(){',
        '  function clearSpaceRoute(){',
        'function buildSpaceRoute(){',
        '  function buildSpaceRoute(){'
    );
}

# 3) Hard-replace clearSpaceRoute
my $clear_fn = <<'JS';
function clearSpaceRoute(){
    state.astro.waypoints = [];
    state.astro.route = null;

    if (typeof clearAstroRouteGraphics === "function") clearAstroRouteGraphics();
    if (typeof clearEarthSpaceRoute === "function") clearEarthSpaceRoute();

    if (typeof renderWaypointList === "function") renderWaypointList();
    if (typeof updateSpaceOutputs === "function") updateSpaceOutputs(null);

    log("Space route cleared");
}
JS

replace_function_block('clearSpaceRoute', $clear_fn);

# 4) Hard-replace buildSpaceRoute
my $build_fn = <<'JS';
function buildSpaceRoute(){
    const start = typeof getSpaceItem === "function"
      ? getSpaceItem($("spaceStartSelect").value)
      : null;
    const end = typeof getSpaceItem === "function"
      ? getSpaceItem($("spaceEndSelect").value)
      : null;

    if (!start || !end) {
      log("Space route build failed: missing start or end node");
      return;
    }

    state.astro.waypoints = [
      JSON.parse(JSON.stringify(start)),
      JSON.parse(JSON.stringify(end))
    ];

    if (typeof buildRouteFromWaypoints === "function") {
      state.astro.route = buildRouteFromWaypoints(state.astro.waypoints);
    } else {
      state.astro.route = {
        waypoints: state.astro.waypoints,
        legs: [],
        totalLy: 0
      };
    }

    if (typeof drawAstroRoute === "function") drawAstroRoute(state.astro.route);
    if (typeof drawEarthSpaceRoute === "function") drawEarthSpaceRoute(state.astro.route);
    if (typeof renderWaypointList === "function") renderWaypointList();
    if (typeof updateSpaceOutputs === "function") updateSpaceOutputs(state.astro.route);

    log(`Space route built: ${start.name} -> ${end.name}`);
}
JS

replace_function_block('buildSpaceRoute', $build_fn);

open my $out, '>', $file or die "Cannot write $file: $!";
print {$out} $html;
close $out;

print "\nDone.\nPatched file: $file\n";

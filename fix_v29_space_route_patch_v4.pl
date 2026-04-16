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
    my $bak = $path . '.bak_space_v4';
    open my $out, '>', $bak or die "Cannot write backup $bak: $!";
    print {$out} $content;
    close $out;
    print "Backup written: $bak\n";
}

sub insert_after_first_found {
    my ($label, $insert, @anchors) = @_;
    for my $anchor (@anchors) {
        my $pos = index($html, $anchor);
        next if $pos < 0;
        $pos += length($anchor);
        substr($html, $pos, 0, $insert);
        print "Inserted: $label\n";
        return 1;
    }
    die "Patch failed: $label (no anchor found)\n";
}

sub insert_before_first_found {
    my ($label, $insert, @anchors) = @_;
    for my $anchor (@anchors) {
        my $pos = index($html, $anchor);
        next if $pos < 0;
        substr($html, $pos, 0, $insert);
        print "Inserted: $label\n";
        return 1;
    }
    die "Patch failed: $label (no anchor found)\n";
}

sub replace_once {
    my ($label, $pattern, $replacement) = @_;
    my $count = ($html =~ s/$pattern/$replacement/s);
    die "Patch failed: $label\n" unless $count;
    print "Patched: $label\n";
}

backup_file($file, $html);

# 1) Add missing astro route state, only if absent
if (index($html, 'earthRoute2d') < 0) {
    my $added = 0;

    if ($html =~ /(cursorDec:\s*null\s*\n\s*)(\}\s*,)/s) {
        $html =~ s/(cursorDec:\s*null\s*\n\s*)(\}\s*,)/
$1      earthRoute2d: null,
      earthRoute2dMarkers: null,
      earthRoute3d: null
$2/s;
        print "Patched: add astro projected-route state after cursorDec\n";
        $added = 1;
    }
    elsif ($html =~ /(currentCatalogFilter:\s*"all"\s*,\s*\n)(\s*\}\s*,)/s) {
        $html =~ s/(currentCatalogFilter:\s*"all"\s*,\s*\n)(\s*\}\s*,)/
$1      earthRoute2d: null,
      earthRoute2dMarkers: null,
      earthRoute3d: null
$2/s;
        print "Patched: add astro projected-route state after currentCatalogFilter\n";
        $added = 1;
    }
    elsif ($html =~ /(astro:\s*\{\s*\n)/s) {
        $html =~ s/(astro:\s*\{\s*\n)/$1      earthRoute2d: null,\n      earthRoute2dMarkers: null,\n      earthRoute3d: null,\n/s;
        print "Patched: add astro projected-route state at top of astro block\n";
        $added = 1;
    }

    die "Patch failed: add astro projected-route state\n" unless $added;
}

# 2) Add projected 2D/3D helpers if absent
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

# 3) Ensure buildSpaceRoute draws projected route
if (index($html, 'drawEarthSpaceRoute(state.astro.route);') < 0) {
    if ($html =~ /function buildSpaceRoute\(\)\s*\{.*?drawAstroRoute\(state\.astro\.route\);\s*/s) {
        $html =~ s/(function buildSpaceRoute\(\)\s*\{.*?drawAstroRoute\(state\.astro\.route\);\s*)/$1    drawEarthSpaceRoute(state.astro.route);\n/s;
        print "Patched: buildSpaceRoute draws 2D/3D projected route\n";
    } else {
        die "Patch failed: buildSpaceRoute draws 2D/3D projected route\n";
    }
}

# 4) Ensure clearSpaceRoute clears projected route
if (index($html, 'clearEarthSpaceRoute();') < 0) {
    if ($html =~ /function clearSpaceRoute\(\)\s*\{.*?clearAstroRouteGraphics\(\);\s*/s) {
        $html =~ s/(function clearSpaceRoute\(\)\s*\{.*?clearAstroRouteGraphics\(\);\s*)/$1    clearEarthSpaceRoute();\n/s;
        print "Patched: clearSpaceRoute clears 2D/3D projected route\n";
    } else {
        die "Patch failed: clearSpaceRoute clears 2D/3D projected route\n";
    }
}

open my $out, '>', $file or die "Cannot write $file: $!";
print {$out} $html;
close $out;

print "\nDone.\nPatched file: $file\n";

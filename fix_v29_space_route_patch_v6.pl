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
    my $bak = $path . '.bak_space_v6';
    open my $out, '>', $bak or die "Cannot write backup $bak: $!";
    print {$out} $content;
    close $out;
    print "Backup written: $bak\n";
}

sub find_matching_brace {
    my ($text, $open_pos) = @_;
    my $len = length($text);
    my $depth = 0;
    my $i = $open_pos;

    my $in_sq = 0;
    my $in_dq = 0;
    my $in_tq = 0;
    my $in_line_comment = 0;
    my $in_block_comment = 0;
    my $escape = 0;

    while ($i < $len) {
        my $ch  = substr($text, $i, 1);
        my $ch2 = ($i + 1 < $len) ? substr($text, $i, 2) : '';

        if ($in_line_comment) {
            if ($ch eq "\n") { $in_line_comment = 0; }
            $i++;
            next;
        }

        if ($in_block_comment) {
            if ($ch2 eq '*/') { $in_block_comment = 0; $i += 2; next; }
            $i++;
            next;
        }

        if ($in_sq) {
            if (!$escape && $ch eq "'") { $in_sq = 0; }
            $escape = (!$escape && $ch eq '\\') ? 1 : 0;
            $i++;
            next;
        }

        if ($in_dq) {
            if (!$escape && $ch eq '"') { $in_dq = 0; }
            $escape = (!$escape && $ch eq '\\') ? 1 : 0;
            $i++;
            next;
        }

        if ($in_tq) {
            if (!$escape && $ch eq '`') { $in_tq = 0; }
            $escape = (!$escape && $ch eq '\\') ? 1 : 0;
            $i++;
            next;
        }

        if ($ch2 eq '//') { $in_line_comment = 1; $i += 2; next; }
        if ($ch2 eq '/*') { $in_block_comment = 1; $i += 2; next; }

        if ($ch eq "'") { $in_sq = 1; $escape = 0; $i++; next; }
        if ($ch eq '"') { $in_dq = 1; $escape = 0; $i++; next; }
        if ($ch eq '`') { $in_tq = 1; $escape = 0; $i++; next; }

        if ($ch eq '{') {
            $depth++;
        } elsif ($ch eq '}') {
            $depth--;
            return $i if $depth == 0;
        }

        $i++;
    }

    die "Unmatched brace while parsing function block\n";
}

sub replace_named_function {
    my ($name, $replacement) = @_;
    my $needle = "function $name(";
    my $start = index($html, $needle);
    die "Patch failed: cannot find function $name\n" if $start < 0;

    my $brace = index($html, '{', $start);
    die "Patch failed: cannot find opening brace for $name\n" if $brace < 0;

    my $end = find_matching_brace($html, $brace);
    substr($html, $start, $end - $start + 1, $replacement);
    print "Patched: replace function $name\n";
}

sub insert_before_first {
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

sub insert_after_first {
    my ($label, $insert, @anchors) = @_;
    for my $anchor (@anchors) {
        my $pos = index($html, $anchor);
        next if $pos < 0;
        $pos += length($anchor);
        substr($html, $pos, 0, $insert);
        print "Inserted: $label\n";
        return 1;
    }
    die "Patch failed: $label\n";
}

backup_file($file, $html);

# 1) Add missing astro state if needed
if (index($html, 'earthRoute2d') < 0) {
    my $needle = "      cursorDec: null";
    my $pos = index($html, $needle);
    if ($pos >= 0) {
        $pos += length($needle);
        substr($html, $pos, 0, ",\n      earthRoute2d: null,\n      earthRoute2dMarkers: null,\n      earthRoute3d: null");
        print "Patched: add astro route state\n";
    } else {
        my $needle2 = "      currentCatalogFilter:";
        my $pos2 = index($html, $needle2);
        die "Patch failed: add astro route state\n" if $pos2 < 0;
        substr($html, $pos2, 0, "      earthRoute2d: null,\n      earthRoute2dMarkers: null,\n      earthRoute3d: null,\n");
        print "Patched: add astro route state\n";
    }
}

# 2) Insert helper functions if missing
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
      try { state.viewer3d.flyTo(ds, { duration: 1.6 }); } catch {}
      state.viewer3d.scene.requestRender();
    }
  }

JS

    insert_before_first(
        'earth-space route helpers',
        $helpers,
        '  function clearSpaceRoute(){',
        'function clearSpaceRoute(){',
        '  function buildSpaceRoute(){',
        'function buildSpaceRoute(){'
    );
}

# 3) Replace clearSpaceRoute robustly
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

replace_named_function('clearSpaceRoute', $clear_fn);

# 4) Replace buildSpaceRoute robustly
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

replace_named_function('buildSpaceRoute', $build_fn);

# 5) Make sure the buttons are wired
if (index($html, '$("spaceBuildBtn").onclick') < 0) {
    my $wire = <<'JS';

    $("spaceBuildBtn").onclick = () => {
      try { buildSpaceRoute(); } catch (e) { log(`Space route failed: ${e.message}`); }
    };
    $("spaceClearBtn").onclick = () => {
      try { clearSpaceRoute(); } catch (e) { log(`Space clear failed: ${e.message}`); }
    };
    $("spaceCenterEarthBtn").onclick = () => {
      try {
        $("spaceStartSelect").value = "earth";
        if (state.mode !== "astro") showMode("astro");
        state.astro.target = "Earth";
        updateSpaceOutputs(state.astro.route || null);
      } catch (e) {
        log(`Space Earth-center failed: ${e.message}`);
      }
    };
    $("spaceCatalogSelect").onchange = () => {
      state.astro.currentCatalogFilter = $("spaceCatalogSelect").value;
      try { renderCatalogMarkers(); } catch (e) { log(`Catalog refresh failed: ${e.message}`); }
    };
    $("spaceShowCatalogChk").onchange = () => {
      try { renderCatalogMarkers(); } catch (e) { log(`Catalog toggle failed: ${e.message}`); }
    };

JS

    insert_after_first(
        'space button wiring',
        $wire,
        '    $("satellitesChk").onchange = () => setSatellites($("satellitesChk").checked).catch(()=>{});',
        '    $("satellitesChk").onchange = () => setSatellites($("satellitesChk").checked).catch(()=>{});' . "\r"
    );
}

# 6) Make sure selectors are populated during boot
if (index($html, 'fillSpaceSelectors();') < 0) {
    insert_after_first(
        'fill space selectors at boot',
        "\n    fillSpaceSelectors();\n    renderWaypointList();\n    updateSpaceOutputs(null);\n",
        '    $("astroSearchBox").value = state.astro.target;',
        '    $("astroSearchBox").value = state.astro.target;' . "\r"
    );
}

open my $out, '>', $file or die "Cannot write $file: $!";
print {$out} $html;
close $out;

print "\nDone.\nPatched file: $file\n";

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
    my $bak = $path . '.bak_space_v8';
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
    my ($in_sq,$in_dq,$in_tq,$in_line,$in_block,$esc) = (0,0,0,0,0,0);

    while ($i < $len) {
        my $ch  = substr($text, $i, 1);
        my $ch2 = ($i + 1 < $len) ? substr($text, $i, 2) : '';

        if ($in_line) {
            $in_line = 0 if $ch eq "\n";
            $i++;
            next;
        }
        if ($in_block) {
            if ($ch2 eq '*/') { $in_block = 0; $i += 2; next; }
            $i++;
            next;
        }
        if ($in_sq) {
            if (!$esc && $ch eq "'") { $in_sq = 0; }
            $esc = (!$esc && $ch eq '\\') ? 1 : 0;
            $i++;
            next;
        }
        if ($in_dq) {
            if (!$esc && $ch eq '"') { $in_dq = 0; }
            $esc = (!$esc && $ch eq '\\') ? 1 : 0;
            $i++;
            next;
        }
        if ($in_tq) {
            if (!$esc && $ch eq '`') { $in_tq = 0; }
            $esc = (!$esc && $ch eq '\\') ? 1 : 0;
            $i++;
            next;
        }

        if ($ch2 eq '//') { $in_line = 1; $i += 2; next; }
        if ($ch2 eq '/*') { $in_block = 1; $i += 2; next; }
        if ($ch eq "'") { $in_sq = 1; $esc = 0; $i++; next; }
        if ($ch eq '"') { $in_dq = 1; $esc = 0; $i++; next; }
        if ($ch eq '`') { $in_tq = 1; $esc = 0; $i++; next; }

        if ($ch eq '{') { $depth++; }
        elsif ($ch eq '}') {
            $depth--;
            return $i if $depth == 0;
        }
        $i++;
    }

    die "Unmatched brace while parsing\n";
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

sub replace_once {
    my ($label, $from, $to) = @_;
    my $count = ($html =~ s/\Q$from\E/$to/s);
    die "Patch failed: $label\n" unless $count;
    print "Patched: $label\n";
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

# 1) Strengthen drawEarthSpaceRoute so it visibly redraws in 2D/3D
my $draw_fn = <<'JS';
function drawEarthSpaceRoute(route){
    clearEarthSpaceRoute();
    if (!route || !route.waypoints || route.waypoints.length < 2) {
      log("Earth/3D projected route skipped: not enough waypoints");
      return;
    }

    const latlngs = route.waypoints.map(wp => {
      const p = projectRaDecToLatLon(wp.ra, wp.dec);
      return [p.lat, p.lon];
    });

    if (state.map2d && latlngs.length >= 2) {
      state.astro.earthRoute2d = L.polyline(latlngs, {
        pane: "overlay",
        color: "#7dd3fc",
        weight: 5,
        opacity: 0.95,
        dashArray: "10 8"
      }).addTo(state.map2d);

      const markers = latlngs.map((pt, i) => {
        const wp = route.waypoints[i];
        return L.circleMarker(pt, {
          pane: "overlay",
          radius: i === 0 ? 8 : 7,
          color: i === 0 ? "#22c55e" : "#eab308",
          fillColor: i === 0 ? "#22c55e" : "#eab308",
          fillOpacity: 0.98,
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

      setTimeout(() => {
        try { state.map2d.invalidateSize(true); } catch {}
      }, 80);
    }

    if (state.viewer3d && latlngs.length >= 2) {
      const ds = new Cesium.CustomDataSource("earthSpaceRoute");
      const positions = latlngs.map((pt, i) =>
        Cesium.Cartesian3.fromDegrees(pt[1], pt[0], 300000 + i * 250000)
      );

      ds.entities.add({
        polyline: {
          positions,
          width: 5,
          material: Cesium.Color.DEEPSKYBLUE.withAlpha(0.98)
        }
      });

      latlngs.forEach((pt, i) => {
        ds.entities.add({
          position: Cesium.Cartesian3.fromDegrees(pt[1], pt[0], 300000 + i * 250000),
          point: {
            pixelSize: i === 0 ? 11 : 9,
            color: i === 0 ? Cesium.Color.LIME : Cesium.Color.YELLOW
          }
        });
      });

      state.viewer3d.dataSources.add(ds);
      state.astro.earthRoute3d = ds;

      try { state.viewer3d.flyTo(ds, { duration: 1.6 }); } catch {}
      try { state.viewer3d.scene.requestRender(); } catch {}
    }

    log(`Earth/3D projected route drawn with ${route.waypoints.length} waypoint(s)`);
}
JS

replace_named_function('drawEarthSpaceRoute', $draw_fn);

# 2) Force buildSpaceRoute to redraw all route layers and switch to astro if needed
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
      state.astro.route = { waypoints: state.astro.waypoints, legs: [], totalLy: 0 };
    }

    try { ensureAstro(); } catch {}
    try { drawAstroRoute(state.astro.route); } catch (e) { log(`drawAstroRoute failed: ${e.message}`); }
    try { drawEarthSpaceRoute(state.astro.route); } catch (e) { log(`drawEarthSpaceRoute failed: ${e.message}`); }
    try { renderWaypointList(); } catch {}
    try { updateSpaceOutputs(state.astro.route); } catch {}

    if (state.mode === "2d" && state.map2d) {
      setTimeout(() => { try { state.map2d.invalidateSize(true); } catch {} }, 100);
    }
    if (state.mode === "3d" && state.viewer3d) {
      setTimeout(() => {
        try { state.viewer3d.resize(); } catch {}
        try { state.viewer3d.scene.requestRender(); } catch {}
      }, 100);
    }

    log(`Space route built: ${start.name} -> ${end.name}`);
}
JS

replace_named_function('buildSpaceRoute', $build_fn);

# 3) Force mode switching to re-show projected route
my $showmode_fn = <<'JS';
function showMode(mode){
    state.mode = mode;
    $("mode2d").classList.toggle("active", mode === "2d");
    $("mode3d").classList.toggle("active", mode === "3d");
    $("modeAstro").classList.toggle("active", mode === "astro");
    updateModeBadge();

    $("map2d").style.display = mode === "2d" ? "block" : "none";
    $("map3d").style.display = mode === "3d" ? "block" : "none";
    $("astroWrap").style.display = mode === "astro" ? "block" : "none";

    if (mode === "2d" && state.map2d) {
      setTimeout(() => {
        try { state.map2d.invalidateSize(true); } catch {}
        if (state.astro.route) {
          try { drawEarthSpaceRoute(state.astro.route); } catch {}
        }
      }, 80);
    }

    if (mode === "3d") {
      ensureViewer();
      setTimeout(() => {
        try { state.viewer3d.resize(); } catch {}
        try { state.viewer3d.scene.requestRender(); } catch {}
        if (state.astro.route) {
          try { drawEarthSpaceRoute(state.astro.route); } catch {}
        }
      }, 100);
    }

    if (mode === "astro") {
      ensureAstro();
      setTimeout(() => {
        try { astroApply(); } catch {}
        if (state.astro.route) {
          try { drawAstroRoute(state.astro.route); } catch {}
        }
      }, 60);
    }

    updateHUD();
    if (isMobile()) setPanelHidden(true);
}
JS

replace_named_function('showMode', $showmode_fn);

# 4) Make sure the build button explicitly calls the patched function
replace_once(
    'force spaceBuildBtn onclick wrapper',
    '$("spaceBuildBtn").onclick = buildSpaceRoute;',
    '$("spaceBuildBtn").onclick = () => { try { buildSpaceRoute(); } catch (e) { log(`Space route failed: ${e.message}`); } };'
);

# 5) Add a debug log after selectors are filled
insert_after_first(
    'space selector debug log',
    "\n    log(`Space selectors ready: ${\$("spaceStartSelect") ? \"ok\" : \"missing\"}`);\n",
    '    $("spaceStartSelect").value = "earth";'
);

open my $out, '>', $file or die "Cannot write $file: $!";
print {$out} $html;
close $out;

print "\nDone.\nPatched file: $file\n";

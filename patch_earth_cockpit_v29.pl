#!/usr/bin/env perl
use strict;
use warnings;
use utf8;
use File::Copy qw(copy);

my $file = shift || 'earth-cockpit-v29.html';
die "File not found: $file\n" unless -f $file;

my $bak = "$file.bak";
copy($file, $bak) or die "Backup failed: $!";

open my $in, '<:raw', $file or die "Open failed: $!";
local $/;
my $html = <$in>;
close $in;

my $changed = 0;

sub patch {
    my ($ref, $regex, $replace, $label) = @_;
    my $count = ($$ref =~ s/$regex/$replace/s);
    print(($count ? "[patched] " : "[skip] ")."$label\n");
    $changed += $count;
}

# 1) Force 2D pane visibility and stacking.
if ($html !~ /#map2d\{[^}]*z-index:\s*1/s) {
    patch(
        \$html,
        qr/#map2d,#map3d,#astroWrap\{\s*position:absolute;\s*inset:0;\s*width:100%;\s*height:100%;\s*background:#000;\s*\}/,
        qq/#map2d,#map3d,#astroWrap{
      position:absolute;
      inset:0;
      width:100%;
      height:100%;
      background:#000;
    }

    #map2d{
      display:block;
      z-index:1;
      min-height:100%;
    }

    #map3d,#astroWrap{
      display:none;
      z-index:2;
    }/,
        '2D/3D/Astro pane z-index repair'
    );
}

# 2) Add dedicated Astro route canvas styling.
if ($html !~ /#astroRouteCanvas/s) {
    patch(
        \$html,
        qr/#astroCanvas\{\s*position:absolute;\s*inset:0;\s*width:100%;\s*height:100%;\s*background:#000;\s*\}/,
        qq/#astroCanvas{
      position:absolute;
      inset:0;
      width:100%;
      height:100%;
      background:#000;
    }

    #astroRouteCanvas{
      position:absolute;
      inset:0;
      width:100%;
      height:100%;
      pointer-events:none;
      z-index:10000;
    }/,
        'Astro route canvas CSS'
    );
}

# 3) Inject route canvas into astroWrap.
if ($html !~ /id="astroRouteCanvas"/) {
    patch(
        \$html,
        qr/<div id="astroWrap">\s*<div id="astroCanvas"><\/div>/,
        qq/<div id="astroWrap">
        <div id="astroCanvas"></div>
        <canvas id="astroRouteCanvas"></canvas>/,
        'Astro route canvas HTML'
    );
}

# 4) Strengthen init2D.
patch(
    \$html,
    qr/function init2D\(\)\s*\{.*?log\("2D initialized"\);\s*\}/s,
    <<'PERLJS',
function init2D(){
    if (state.map2d) return;

    state.map2d = L.map("map2d", {
      center:[CONFIG.home.lat, CONFIG.home.lon],
      zoom:CONFIG.home.zoom2d,
      worldCopyJump:true,
      zoomControl:true,
      zoomAnimation:true,
      fadeAnimation:false,
      inertia:true,
      preferCanvas:true
    });

    state.map2d.createPane("base");
    state.map2d.getPane("base").style.zIndex = 200;

    state.map2d.createPane("overlay");
    state.map2d.getPane("overlay").style.zIndex = 430;

    state.map2d.createPane("weather");
    state.map2d.getPane("weather").style.zIndex = 500;

    state.map2d.createPane("labels");
    state.map2d.getPane("labels").style.zIndex = 650;

    state.labels2dLayer = makeTileLayer(CONFIG.labels, {
      pane:"labels",
      subdomains:"abcd",
      maxZoom:20,
      attribution:"CARTO"
    });

    state.map2d.on("move zoom zoomend moveend resize", updateHUD);

    requestAnimationFrame(() => state.map2d.invalidateSize(true));
    setTimeout(() => state.map2d.invalidateSize(true), 120);
    setTimeout(() => state.map2d.invalidateSize(true), 350);

    log("2D initialized");
  }
PERLJS
    'init2D hardening'
);

# 5) Strengthen showMode for 2D + Astro.
patch(
    \$html,
    qr/function showMode\(mode\)\s*\{.*?if \(isMobile\(\)\) setPanelHidden\(true\);\s*\}/s,
    <<'PERLJS',
async function showMode(mode){
    state.mode = mode;
    $("mode2d").classList.toggle("active", mode === "2d");
    $("mode3d").classList.toggle("active", mode === "3d");
    $("modeAstro").classList.toggle("active", mode === "astro");
    updateModeBadge();

    $("map2d").style.display = mode === "2d" ? "block" : "none";
    $("map3d").style.display = mode === "3d" ? "block" : "none";
    $("astroWrap").style.display = mode === "astro" ? "block" : "none";

    if (mode === "2d" && state.map2d) {
      requestAnimationFrame(() => state.map2d.invalidateSize(true));
      setTimeout(() => state.map2d.invalidateSize(true), 120);
      setTimeout(() => state.map2d.invalidateSize(true), 320);
    }

    if (mode === "3d") {
      ensureViewer();
      setTimeout(() => {
        state.viewer3d.resize();
        state.viewer3d.scene.requestRender();
      }, 70);
    }

    if (mode === "astro") {
      ensureAstro();
      setTimeout(() => {
        astroApply();
        if (typeof resizeAstroRouteCanvas === "function") resizeAstroRouteCanvas();
        if (typeof updateSkyCenterOut === "function") updateSkyCenterOut();
        if (state.astro.route && typeof drawAstroRouteCanvas === "function") {
          drawAstroRouteCanvas(state.astro.route);
        }
      }, 80);
    }

    updateHUD();
    if (isMobile()) setPanelHidden(true);
  }
PERLJS
    'showMode hardening'
);

# 6) Replace drawAstroRoute with canvas-based drawing.
patch(
    \$html,
    qr/function drawAstroRoute\(route\)\s*\{.*?renderWaypointList\(\);\s*\}/s,
    <<'PERLJS',
function drawAstroRoute(route){
    ensureAstro();
    clearAstroRouteGraphics();
    if (!route || route.waypoints.length < 2) return;

    const routeSources = route.waypoints.map((wp, idx) => A.source(wp.ra, wp.dec, {
      popupTitle:`${idx + 1}. ${wp.name}`,
      popupDesc:`RA ${fmt(wp.ra,4)}°<br>Dec ${fmt(wp.dec,4)}°<br>Distance ${formatSpaceDistance(wp.distanceLy)}<br>Class ${escapeHtml(wp.class)}`
    }));
    state.astro.routeCatalog.addSources(routeSources);

    const last = route.waypoints[route.waypoints.length - 1];
    state.astro.target = last.name;
    $("astroSearchBox").value = last.name;

    try { state.astro.instance.gotoRaDec(last.ra, last.dec); } catch {
      try { state.astro.instance.gotoObject(last.name); } catch {}
    }

    drawAstroRouteCanvas(route);
    updateSpaceOutputs(route);
    renderWaypointList();
  }
PERLJS
    'drawAstroRoute canvas rewrite'
);

# 7) Replace clearAstroRouteGraphics so it clears canvas too.
patch(
    \$html,
    qr/function clearAstroRouteGraphics\(\)\s*\{.*?\}/s,
    <<'PERLJS',
function clearAstroRouteGraphics(){
    if (state.astro.routeCatalog) {
      try { state.astro.routeCatalog.clear(); } catch {}
    }
    if (state.astro.overlay) {
      try { state.astro.overlay.removeAll(); } catch {}
    }
    const canvas = $("astroRouteCanvas");
    if (canvas) {
      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
  }
PERLJS
    'clearAstroRouteGraphics canvas clear'
);

# 8) Inject Astro route canvas helpers before wireUI().
if ($html !~ /function drawAstroRouteCanvas\(route\)/s) {
    patch(
        \$html,
        qr/function wireUI\(\)\s*\{/,
        <<'PERLJS',
function resizeAstroRouteCanvas(){
    const canvas = $("astroRouteCanvas");
    const host = $("astroWrap");
    if (!canvas || !host) return;
    const w = Math.max(1, host.clientWidth);
    const h = Math.max(1, host.clientHeight);
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }
  }

  function astroWorldToCanvas(ra, dec){
    if (!state.astro.instance || !state.astro.instance.world2pix) return null;
    try {
      const p = state.astro.instance.world2pix(ra, dec);
      if (!Array.isArray(p) || p.length < 2) return null;
      if (!Number.isFinite(p[0]) || !Number.isFinite(p[1])) return null;
      return { x:p[0], y:p[1] };
    } catch {
      return null;
    }
  }

  function drawAstroRouteCanvas(route){
    const canvas = $("astroRouteCanvas");
    if (!canvas || !route || !route.waypoints || route.waypoints.length < 2) return;

    resizeAstroRouteCanvas();
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const pts = route.waypoints.map(wp => astroWorldToCanvas(wp.ra, wp.dec)).filter(Boolean);
    if (pts.length < 2) return;

    ctx.save();
    ctx.lineWidth = 3;
    ctx.strokeStyle = "#38bdf8";
    ctx.fillStyle = "#22c55e";
    ctx.shadowColor = "rgba(56,189,248,0.9)";
    ctx.shadowBlur = 10;

    ctx.beginPath();
    ctx.moveTo(pts[0].x, pts[0].y);
    for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y);
    ctx.stroke();

    ctx.shadowBlur = 0;
    for (let i = 0; i < pts.length; i++) {
      ctx.beginPath();
      ctx.arc(pts[i].x, pts[i].y, i === 0 ? 6 : 5, 0, Math.PI * 2);
      ctx.fillStyle = i === 0 ? "#22c55e" : (i === pts.length - 1 ? "#ef4444" : "#facc15");
      ctx.fill();
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 1.5;
      ctx.stroke();

      ctx.fillStyle = "#ffffff";
      ctx.font = "12px system-ui";
      ctx.fillText(String(i + 1), pts[i].x + 8, pts[i].y - 8);
    }

    ctx.restore();
  }

function wireUI(){
PERLJS
        'Astro canvas helper injection'
    );
}

# 9) Redraw Astro route after resize.
patch(
    \$html,
    qr/window\.addEventListener\("resize",\s*\(\)\s*=>\s*\{.*?\n\s*\}\);/s,
    <<'PERLJS',
window.addEventListener("resize", () => {
      syncPanel();
      if (state.map2d && state.mode === "2d") {
        setTimeout(() => state.map2d.invalidateSize(true), 30);
        setTimeout(() => state.map2d.invalidateSize(true), 180);
      }
      if (state.viewer3d && state.mode === "3d") {
        setTimeout(() => {
          state.viewer3d.resize();
          state.viewer3d.scene.requestRender();
        }, 30);
      }
      if (state.mode === "astro") {
        setTimeout(() => {
          if (typeof resizeAstroRouteCanvas === "function") resizeAstroRouteCanvas();
          if (state.astro.route && typeof drawAstroRouteCanvas === "function") {
            drawAstroRouteCanvas(state.astro.route);
          }
          if (typeof updateSkyCenterOut === "function") updateSkyCenterOut();
        }, 60);
      }
    });
PERLJS
    'Resize handler upgrade'
);

# 10) Ensure overlay opacity control exists.
if ($html !~ /id="overlayOpacity"/) {
    patch(
        \$html,
        qr/<div class="box">\s*<div class="tiny"><b>Hazards<\/b><\/div>.*?<\/div>\s*<\/div>/s,
        qq/$&

      <div class="box">
        <div class="tiny"><b>Overlay opacity</b></div>
        <div class="row">
          <input id="overlayOpacity" type="range" min="0" max="100" value="72">
        </div>
      </div>/,
        'Overlay opacity block'
    );
}

# 11) Make sure boot resizes 2D and Astro canvas.
patch(
    \$html,
    qr/await showMode\("2d"\);\s*\n\s*setStatus\("Ready", "ok"\);/s,
    <<'PERLJS',
await showMode("2d");
    setTimeout(() => {
      if (state.map2d) state.map2d.invalidateSize(true);
      if (typeof resizeAstroRouteCanvas === "function") resizeAstroRouteCanvas();
    }, 150);

    setStatus("Ready", "ok");
PERLJS
    'boot resize repair'
);

open my $out, '>:raw', $file or die "Write failed: $!";
print {$out} $html;
close $out;

print "\nBackup written to: $bak\n";
print "Patched file written to: $file\n";
print $changed ? "Done.\n" : "No matching sections were replaced. Your file may differ from the expected v29 layout.\n";

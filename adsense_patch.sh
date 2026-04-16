#!/usr/bin/env bash
set -euo pipefail

# Use the current directory (where you run the script)
SITE_DIR="$(pwd)"
cd "$SITE_DIR"

echo "== Living Apps: adding AdSense-ready content pages =="
ts="$(date +%Y%m%d_%H%M%S)"
mkdir -p _backup
cp -a index.html "_backup/index.html.$ts.bak" || true

cat > how-it-works.html <<'HTML'
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>How Living Apps Work • DS-DS-ship-it</title>
  <meta name="description" content="Technical breakdown of the Living Apps demos: audio processing, FFT frequency bands, mode architecture, file loading, and mobile compatibility." />
  <style>
    :root { color-scheme: dark; }
    body { margin:0; font:16px/1.55 system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial; background:#0b0c10; color:#e9eef5; }
    header { padding:28px 16px 10px; border-bottom:1px solid rgba(255,255,255,.08); background:rgba(15,18,24,.7); backdrop-filter: blur(10px); position:sticky; top:0; }
    header .wrap { max-width:980px; margin:0 auto; display:flex; gap:14px; align-items:center; justify-content:space-between; }
    a { color:#86b7ff; text-decoration:none; }
    a:hover { text-decoration:underline; }
    main { max-width:980px; margin:0 auto; padding:20px 16px 60px; }
    h1,h2,h3 { line-height:1.2; }
    .card { border:1px solid rgba(255,255,255,.10); border-radius:14px; background:rgba(15,18,24,.55); padding:16px; margin:14px 0; }
    code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; font-size: 13.5px; }
    pre { background:#07090f; border:1px solid rgba(255,255,255,.10); border-radius:12px; padding:12px; overflow:auto; }
    .muted { color: rgba(233,238,245,.72); }
    .pill { display:inline-block; border:1px solid rgba(255,255,255,.12); border-radius:999px; padding:6px 10px; margin:4px 6px 0 0; background:rgba(255,255,255,.04); font-size:13px; }
    ul { margin: 10px 0 10px 20px; }
  </style>
</head>
<body>
<header>
  <div class="wrap">
    <div>
      <div class="muted" style="font-size:13px;">DS-DS-ship-it • Living Apps</div>
      <div style="font-weight:700;">How it works (technical)</div>
    </div>
    <nav style="display:flex; gap:12px; flex-wrap:wrap; justify-content:flex-end;">
      <a href="./index.html">Home</a>
      <a href="./living-artwork/">Living Artwork</a>
      <a href="./video-artwork-living/">Video Artwork Living</a>
      <a href="./audio-artwork-living/">Audio Artwork Living</a>
      <a href="./about.html">About</a>
      <a href="./privacy.html">Privacy</a>
    </nav>
  </div>
</header>

<main>
  <h1>Living Apps: a practical technical breakdown</h1>
  <p class="muted">
    This page explains how the public demos on this site work. The demos you run on GitHub Pages are the
    <strong>base programs</strong> (Living Artwork, Video Artwork Living, Audio Artwork Living). They provide
    real-time visual generation and audio-reactive behavior using standard web APIs. Additional experimental
    plugins may exist during development, but this public site focuses on the stable base experience.
  </p>

  <div class="card">
    <span class="pill">HTML5 Canvas</span>
    <span class="pill">Web Audio API</span>
    <span class="pill">FFT</span>
    <span class="pill">Frequency Bands</span>
    <span class="pill">Mobile-first controls</span>
    <span class="pill">No account required</span>
    <p>
      The “Living” effect comes from combining (1) a continuously rendered visual scene, and (2) a stream of
      measurements taken from either your microphone, a loaded audio file, or other inputs like video pixels.
      Those measurements are transformed into stable “control signals” that drive motion, color, geometry,
      and scene decisions.
    </p>
  </div>

  <h2>1) Audio processing: how sound becomes visual motion</h2>
  <p>Most audio-reactive scenes follow the same pipeline:</p>
  <ul>
    <li><strong>Acquire audio</strong> from microphone or a media element.</li>
    <li><strong>Analyze</strong> the audio stream using FFT and time-domain measures.</li>
    <li><strong>Extract features</strong> such as bass/mid/treble energy, RMS loudness, and beat-like events.</li>
    <li><strong>Smooth</strong> the features so visuals respond without jitter.</li>
    <li><strong>Map</strong> features into visual parameters (radius, rotation, glow, motion, etc.).</li>
  </ul>

  <div class="card">
    <h3>FFT in plain language</h3>
    <p>
      FFT converts sound from “wave over time” into “energy by frequency.” In browsers this is commonly done with
      <code>AnalyserNode</code>. The analyser produces a spectrum array (frequency bins), which you can average
      into band energies for stable visual control.
    </p>
    <p class="muted">
      Note: bins are not musical notes; they’re evenly spaced slices across the frequency range.
    </p>
  </div>

  <h3>Frequency bands</h3>
  <ul>
    <li><strong>Bass</strong> (~20–140 Hz): kick drums, low rumbles.</li>
    <li><strong>Mids</strong> (~140–2000 Hz): vocals, guitars, “presence”.</li>
    <li><strong>Treble</strong> (~2000–16000 Hz): sparkle and “air”.</li>
  </ul>

  <h2>2) Plugins and JS modules (public site vs development)</h2>
  <p>
    During development you may experiment with plugins or injected modes. However, the public GitHub Pages demos
    are designed to run as stable base apps without requiring plugin installation. Mobile browsers (especially iOS Safari)
    can restrict file picking and dynamic code injection, so public pages should only claim features that are actually shipped.
  </p>

  <h2>3) Mobile compatibility (iPhone + iPad + laptops)</h2>
  <ul>
    <li><strong>User gesture required</strong> to start audio contexts (mic/playback).</li>
    <li>Microphone prompts must be triggered by a direct tap/click.</li>
    <li>Canvas DPR scaling should be capped to reduce heat/battery drain.</li>
    <li>iOS file pickers may hide uncommon extensions; HTML wrappers are often more compatible.</li>
  </ul>

  <h2>4) Summary</h2>
  <p>
    The Living Apps demos are interactive visuals driven by Web Audio analysis (FFT + bands + smoothing) and rendered
    to Canvas in real time. These pages provide “publisher content” and a better user experience for AdSense review.
  </p>
</main>
</body>
</html>
HTML

cat > about.html <<'HTML'
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>About • DS-DS-ship-it Living Apps</title>
  <meta name="description" content="About DS-DS-ship-it Living Apps: browser-based generative artwork demos for audio, video, and interactive experimentation." />
  <style>
    :root { color-scheme: dark; }
    body { margin:0; font:16px/1.55 system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial; background:#0b0c10; color:#e9eef5; }
    header { padding:28px 16px 10px; border-bottom:1px solid rgba(255,255,255,.08); background:rgba(15,18,24,.7); backdrop-filter: blur(10px); position:sticky; top:0; }
    header .wrap { max-width:980px; margin:0 auto; display:flex; gap:14px; align-items:center; justify-content:space-between; }
    a { color:#86b7ff; text-decoration:none; }
    a:hover { text-decoration:underline; }
    main { max-width:980px; margin:0 auto; padding:20px 16px 60px; }
    .card { border:1px solid rgba(255,255,255,.10); border-radius:14px; background:rgba(15,18,24,.55); padding:16px; margin:14px 0; }
    .muted { color: rgba(233,238,245,.72); }
  </style>
</head>
<body>
<header>
  <div class="wrap">
    <div>
      <div class="muted" style="font-size:13px;">DS-DS-ship-it • Living Apps</div>
      <div style="font-weight:700;">About</div>
    </div>
    <nav style="display:flex; gap:12px; flex-wrap:wrap; justify-content:flex-end;">
      <a href="./index.html">Home</a>
      <a href="./how-it-works.html">How it works</a>
      <a href="./privacy.html">Privacy</a>
    </nav>
  </div>
</header>

<main>
  <h1>About DS-DS-ship-it Living Apps</h1>
  <div class="card">
    <p>
      Living Apps is a collection of browser-based creative demos that transform audio and video input into evolving
      animated visuals. Everything runs locally in your browser using standard web APIs (Canvas + Web Audio).
    </p>
    <p class="muted">
      The public site focuses on stable base programs. Experimental plugin systems may exist in development builds, but
      are not required for the hosted demos to run.
    </p>
  </div>

  <p>Explore:</p>
  <ul>
    <li><a href="./living-artwork/">Living Artwork</a></li>
    <li><a href="./video-artwork-living/">Video Artwork Living</a></li>
    <li><a href="./audio-artwork-living/">Audio Artwork Living</a></li>
  </ul>
</main>
</body>
</html>
HTML

cat > privacy.html <<'HTML'
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Privacy Policy • DS-DS-ship-it Living Apps</title>
  <meta name="description" content="Privacy policy for DS-DS-ship-it Living Apps, including microphone usage, local processing, and advertising disclosures." />
  <style>
    :root { color-scheme: dark; }
    body { margin:0; font:16px/1.55 system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial; background:#0b0c10; color:#e9eef5; }
    header { padding:28px 16px 10px; border-bottom:1px solid rgba(255,255,255,.08); background:rgba(15,18,24,.7); backdrop-filter: blur(10px); position:sticky; top:0; }
    header .wrap { max-width:980px; margin:0 auto; display:flex; gap:14px; align-items:center; justify-content:space-between; }
    a { color:#86b7ff; text-decoration:none; }
    a:hover { text-decoration:underline; }
    main { max-width:980px; margin:0 auto; padding:20px 16px 60px; }
    .card { border:1px solid rgba(255,255,255,.10); border-radius:14px; background:rgba(15,18,24,.55); padding:16px; margin:14px 0; }
    .muted { color: rgba(233,238,245,.72); }
    ul { margin: 10px 0 10px 20px; }
  </style>
</head>
<body>
<header>
  <div class="wrap">
    <div>
      <div class="muted" style="font-size:13px;">DS-DS-ship-it • Living Apps</div>
      <div style="font-weight:700;">Privacy Policy</div>
    </div>
    <nav style="display:flex; gap:12px; flex-wrap:wrap; justify-content:flex-end;">
      <a href="./index.html">Home</a>
      <a href="./how-it-works.html">How it works</a>
      <a href="./about.html">About</a>
    </nav>
  </div>
</header>

<main>
  <h1>Privacy Policy</h1>
  <p class="muted">Last updated: <span id="d"></span></p>
  <script>document.getElementById('d').textContent = new Date().toISOString().slice(0,10);</script>

  <div class="card">
    <p>
      Microphone access is optional and only enabled after you tap a button that requests permission. Audio analysis
      (FFT and loudness) occurs locally in your browser.
    </p>
  </div>

  <h2>Advertising and cookies</h2>
  <p>
    This site may display advertising (e.g., via Google AdSense). Advertising providers may use cookies or similar
    technologies to show ads, measure performance, and limit frequency.
  </p>

  <h2>Files you choose</h2>
  <p>
    If you load audio/video files, they are used locally by your browser for visualization. The demo does not require
    uploading your files in order to function.
  </p>
</main>
</body>
</html>
HTML

DOC_BLOCK=$(cat <<'BLOCK'
<section style="max-width:980px;margin:18px auto 10px;padding:0 14px;">
  <div style="border:1px solid rgba(255,255,255,.10);background:rgba(15,18,24,.55);backdrop-filter: blur(10px);border-radius:14px;padding:16px;">
    <h2 style="margin:0 0 8px;font-size:18px;">Documentation</h2>
    <p style="margin:0 0 10px;color:rgba(233,238,245,.78);">
      These demos run the <strong>base programs</strong> on GitHub Pages (no plugin installation required). For a technical
      breakdown of audio processing (FFT + frequency bands) and mobile behavior, see:
    </p>
    <ul style="margin:0 0 10px 18px;">
      <li><a href="./how-it-works.html">How it works (technical)</a></li>
      <li><a href="./about.html">About</a></li>
      <li><a href="./privacy.html">Privacy policy</a></li>
    </ul>
  </div>
</section>
BLOCK
)

if grep -q '</main>' index.html; then
  perl -0777 -i -pe "s#</main>#$DOC_BLOCK\n</main>#s" index.html
else
  perl -0777 -i -pe "s#</body>#$DOC_BLOCK\n</body>#s" index.html
fi

echo "== Done. Created: how-it-works.html, about.html, privacy.html and patched index.html =="
echo "Now run:"
echo "  git status"
echo "  git add index.html how-it-works.html about.html privacy.html"
echo "  git commit -m \"Add documentation + policy pages for AdSense\""
echo "  git push"

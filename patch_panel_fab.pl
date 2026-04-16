use strict;
use warnings;

my $file = shift @ARGV or die "Usage: $0 path/to/file.html\n";
local $/;
open my $fh, "<", $file or die "read $file: $!";
my $s = <$fh>;
close $fh;

# Don’t double-apply
if ($s =~ /id="panelFab"/) {
  print "Already patched: $file\n";
  exit 0;
}

# 1) CSS inject before </style>
$s =~ s#</style>#\n
  /* ---- Mobile panel minimize FAB (auto patch) ---- */
  #panelFab{
    position: fixed;
    left: 12px;
    bottom: calc(12px + env(safe-area-inset-bottom, 0px));
    z-index: 999999;
    display: none;
    border-radius: 999px;
    padding: 12px 14px;
    border: 1px solid rgba(255,255,255,.14);
    background: rgba(15,18,24,.72);
    backdrop-filter: blur(10px);
    color: #e9eef5;
    font-weight: 800;
    cursor: pointer;
    box-shadow: 0 18px 60px rgba(0,0,0,.55);
    user-select: none;
  }
  #panelFab.show{
    display: inline-flex;
    align-items:center;
    gap:10px;
  }
  /* Hide panel when minimized (supports your common ids/classes) */
  .panel.minimized, #panel.minimized, .drawer.minimized, #drawer.minimized{
    transform: translateX(calc(-100% - 18px));
    opacity: 0;
    pointer-events: none;
  }

</style>#s or die "Could not find </style>\n";

# 2) HTML inject before </body>
$s =~ s#</body>#\n<button id="panelFab" aria-label="Open panel">☰ Panel</button>\n\n</body>#s
  or die "Could not find </body>\n";

# 3) JS inject before </script>
my $js = <<'JS';
/* ---- Mobile panel minimize behavior (auto patch) ---- */
(function(){
  const fab = document.getElementById("panelFab");

  // Try common panel nodes used in your builds
  const panel =
    document.getElementById("panel") ||
    document.querySelector(".panel") ||
    document.getElementById("drawer") ||
    document.querySelector(".drawer");

  if(!fab || !panel) return;

  function setMinimized(min){
    panel.classList.toggle("minimized", !!min);
    fab.classList.toggle("show", !!min);
  }

  // Hook existing minimize button if present
  const btnMin =
    document.getElementById("btnMin") ||
    panel.querySelector("#btnMin") ||
    panel.querySelector("[data-minimize]");

  if(btnMin){
    btnMin.addEventListener("click", function(){
      setMinimized(!panel.classList.contains("minimized"));
    });
  }

  fab.addEventListener("click", function(){
    setMinimized(false);
  });

  function isMobile(){ return window.matchMedia("(max-width: 720px)").matches; }

  if (window.map && window.map.on){
    window.map.on("movestart", function(){
      if(isMobile()) setMinimized(true);
    });
  } else {
    window.addEventListener("touchstart", function(){
      if(isMobile()) setMinimized(true);
    }, {passive:true});
  }

  if(isMobile()) setMinimized(true);
})();
JS

$s =~ s#</script>#$js\n</script>#s or die "Could not find </script>\n";

open my $out, ">", $file or die "write $file: $!";
print $out $s;
close $out;

print "Patched: $file\n";

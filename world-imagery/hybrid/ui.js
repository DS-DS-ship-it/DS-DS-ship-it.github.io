const $ = (id)=>document.getElementById(id);

export function wireUI(api, state){
  const panel = $("panel");
  const fab = $("fab");

  function setDot(id,on){ const d=$(id); if(!d) return; d.classList.toggle("on", !!on); }

  $("btnMin")?.addEventListener("click", ()=>{
    panel.classList.add("minimized");
    fab.classList.add("show");
  });
  fab?.addEventListener("click", ()=>{
    panel.classList.remove("minimized");
    fab.classList.remove("show");
  });

  $("btn2d")?.addEventListener("click", ()=>api.setMode("2d"));
  $("btn3d")?.addEventListener("click", ()=>api.setMode("3d"));
  $("btnHome")?.addEventListener("click", ()=>api.home());

  $("togRadar")?.addEventListener("click", ()=>api.toggleRadar());
  $("togQuakes")?.addEventListener("click", ()=>api.toggleQuakes());
  $("togFires")?.addEventListener("click", ()=>api.toggleFires());

  $("btnCopy")?.addEventListener("click", ()=>api.copyLink());
  $("btnResetCam")?.addEventListener("click", ()=>api.sync());

  $("togDebug")?.addEventListener("click", ()=>api.toggleDebug());

  // init dots
  setDot("dotRadar", state.layers.radar);
  setDot("dotQuakes", state.layers.quakes);
  setDot("dotFires", state.layers.fires);
  setDot("dotDebug", state.debug);

  // Mobile: auto-minimize so the map is usable
  if (window.matchMedia("(max-width: 720px)").matches) {
    panel.classList.add("minimized");
    fab.classList.add("show");
  }

  return { setDot };
}

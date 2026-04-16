export function loadStateFromURL(){
  const p = new URLSearchParams(location.search);
  const mode = p.get("mode");
  const s = {
    mode: (mode === "3d" || mode === "2d") ? mode : "2d",
    layers: {
      radar: (p.get("radar") || "0") === "1",
      quakes:(p.get("quakes")|| "0") === "1",
      fires: (p.get("fires") || "0") === "1",
    },
    debug: (p.get("debug") || "0") === "1",
  };
  return s;
}

export function saveStateToURL(state){
  const p = new URLSearchParams(location.search);
  p.set("mode", state.mode);
  p.set("radar", state.layers.radar ? "1":"0");
  p.set("quakes", state.layers.quakes ? "1":"0");
  p.set("fires", state.layers.fires ? "1":"0");
  p.set("debug", state.debug ? "1":"0");
  const url = `${location.pathname}?${p.toString()}`;
  history.replaceState(null, "", url);
}

// The theatre. Slice 1 draws dots from each place's lat/lon over the world
// outline; slice 2 adds filled regions when the scenario record carries them.
(function () {
  const C = (window.Casus = window.Casus || {});
  const PALETTE = ["#4fa3ff", "#ff5a6e", "#a98bff", "#f5c451", "#4fd1b5", "#ff9e5e", "#7ee081", "#e07ee0"];
  const CTX = {}; let seq = 0;

  function colour(run, actorId) {
    const i = C.records.actorIds(run).indexOf(actorId);
    return i < 0 ? "#8a95a5" : PALETTE[i % PALETTE.length];
  }
  function places(run) { return run.scenario.places || {}; }
  function coords(p) {
    const a = p.attrs || {};
    return typeof a.lat === "number" && typeof a.lon === "number" ? [a.lon, a.lat] : null;
  }
  function hasMap(run) { return Object.values(places(run)).some((p) => coords(p)); }

  function world() { return window.CASUS_WORLDMAP || { projection: { width: 1000, height: 500 }, countries: {} }; }
  function px(lon) { return ((lon + 180) / 360) * world().projection.width; }
  function py(lat) { return ((90 - lat) / 180) * world().projection.height; }

  function box(run, aspect) {
    const pts = Object.values(places(run)).map(coords).filter(Boolean);
    const xs = pts.map((c) => px(c[0])), ys = pts.map((c) => py(c[1]));
    let x0 = Math.min(...xs) - 7, x1 = Math.max(...xs) + 7, y0 = Math.min(...ys) - 6, y1 = Math.max(...ys) + 6;
    let w = x1 - x0, h = y1 - y0;
    if (w / h < aspect) { const nw = h * aspect; x0 -= (nw - w) / 2; w = nw; }
    else { const nh = w / aspect; y0 -= (nh - h) / 2; h = nh; }
    return { x: x0, y: y0, w, h };
  }

  function strengthAt(run, snap, placeId) {
    const size = ((run.scenario.display || {}).map || {}).size || "strength";
    return (snap.entities || []).filter((e) => e.place === placeId)
      .reduce((s, e) => s + Number((e.attrs || {})[size] || 0), 0);
  }

  function draw(svg, run, snap, opts) {
    opts = opts || {};
    if (!hasMap(run)) { svg.outerHTML = `<div class="nomap">${C.i18n.t("no_map")}</div>`; return; }
    const b = box(run, opts.aspect || 2), S = b.w / 100;
    const ring = ((run.scenario.display || {}).map || {}).ring;
    const cid = opts.ctx ? ++seq : 0;
    if (cid) CTX[cid] = Object.assign({ snapshot: snap }, opts.ctx);
    let o = "";
    for (const [iso, d] of Object.entries(world().countries || {})) {
      o += `<path class="land" d="${d}" stroke-width="${(0.12 * S).toFixed(3)}"/>`;
    }
    if (opts.edges) {
      const seen = new Set();
      for (const [id, p] of Object.entries(places(run))) {
        for (const q of p.adjacency || []) {
          const k = [id, q].sort().join("|"), r = places(run)[q];
          if (seen.has(k) || !r || !coords(p) || !coords(r)) continue; seen.add(k);
          const a = coords(p), c = coords(r);
          o += `<line class="edge" x1="${px(a[0])}" y1="${py(a[1])}" x2="${px(c[0])}" y2="${py(c[1])}" stroke-width="${0.18 * S}" stroke-dasharray="${0.6 * S} ${0.6 * S}"/>`;
        }
      }
    }
    let i = 0;
    for (const [id, p] of Object.entries(places(run))) {
      const c = coords(p); if (!c) continue;
      const x = px(c[0]), y = py(c[1]);
      const st = (snap.places || {})[id] || { owner: p.owner, attrs: p.attrs || {} };
      const r = (0.8 + Math.sqrt(Math.max(strengthAt(run, snap, id), 0)) * 0.28) * S * (opts.rscale || 1);
      const fill = st.owner ? colour(run, st.owner) : "#5a626c";
      if (cid) o += `<g class="pl" data-place="${id}">`;
      const v = ring ? Number((st.attrs || {})[ring] || 0) : 0;
      if (v > 0) {
        const rr = r + 0.9 * S, circ = 2 * Math.PI * rr;
        o += `<circle cx="${x}" cy="${y}" r="${rr}" fill="none" stroke="#ff8a9b" stroke-width="${0.35 * S}" stroke-dasharray="${(Math.min(v, 100) / 100) * circ} ${circ}" transform="rotate(-90 ${x} ${y})"/>`;
      }
      for (const t of (opts.targets || []).filter((t) => t.place === id)) {
        o += `<circle class="target" cx="${x}" cy="${y}" r="${r + 1.4 * S}" stroke="${colour(run, t.actor)}" stroke-width="${0.4 * S}"/>`;
      }
      o += `<circle class="mk" cx="${x}" cy="${y}" r="${r}" fill="${fill}" stroke-width="${0.25 * S}"/>`;
      const flip = i++ % 2 === 1, fs = (opts.font || 1.9) * S;
      if (fs > 0) {
        o += `<text class="plabel" x="${flip ? x - r - S : x + r + S}" y="${y + fs * 0.35}" text-anchor="${flip ? "end" : "start"}" font-size="${fs}" stroke-width="${0.35 * S}">${esc(C.records.label(run, id))}</text>`;
      }
      if (cid) o += `<circle cx="${x}" cy="${y}" r="${r + 2.2 * S}" fill="transparent"/></g>`;
    }
    svg.setAttribute("viewBox", `${b.x} ${b.y} ${b.w} ${b.h}`);
    svg.setAttribute("preserveAspectRatio", `xMidYMid ${opts.slice ? "slice" : "meet"}`);
    if (cid) svg.dataset.ctx = String(cid); else delete svg.dataset.ctx;
    svg.innerHTML = o;
  }

  function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]); }

  C.map = { draw, hasMap, colour, esc, context: (id) => CTX[id] || null };
})();

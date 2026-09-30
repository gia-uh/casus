// The place card: what a place is, who holds it, what is there, what was aimed
// at it, and what changed. It reads the context the map stored when it drew.
(function () {
  const C = (window.Casus = window.Casus || {});
  const t = (k) => C.i18n.t(k);

  function fmt(v) {
    const n = Number(v);
    if (!isFinite(n)) return String(v);
    const s = Math.abs(n) >= 10 || Number.isInteger(n) ? String(Math.round(n)) : n.toFixed(1);
    return C.i18n.lang() === "es" ? s.replace(".", ",") : s;
  }
  function value(a, b, worse) {
    if (b === undefined || Math.abs(b - a) < 0.05) return `<span class="tv">${fmt(a)}</span>`;
    const bad = (b < a) !== !!worse;
    return `<span class="tv ${bad ? "down" : "up"}">${fmt(a)} → ${fmt(b)}</span>`;
  }

  function html(run, placeId, c) {
    const esc = C.map.esc, L = (k) => esc(C.records.label(run, k));
    const d = run.scenario.display || {}, p = (run.scenario.places || {})[placeId] || {};
    const st = (c.snapshot.places || {})[placeId] || { owner: p.owner, attrs: p.attrs || {} };
    const pv = c.prev ? (c.prev.places || {})[placeId] : null;
    const worse = new Set(d.worse_when_higher || []);
    const attrs = (d.card || []).map((k) => {
      const now = Number((st.attrs || {})[k] || 0);
      const was = pv ? Number((pv.attrs || {})[k] || 0) : undefined;
      const max = ((run.scenario.attributes || {})[k] || {}).max || 100;
      const col = worse.has(k) ? "#ff8a9b" : st.owner ? C.map.colour(run, st.owner) : "#8a95a5";
      return `<div class="trow"><span>${L(k)}</span><div class="bar"><i style="width:${Math.min(100, (now / max) * 100)}%;background:${col}"></i></div>${was === undefined ? value(now) : value(was, now, worse.has(k))}</div>`;
    }).join("");
    const size = (d.map || {}).size || "strength";
    const prevE = {}; for (const e of (c.prev ? c.prev.entities : []) || []) prevE[e.id] = e;
    const here = (c.snapshot.entities || []).filter((e) => e.place === placeId);
    const gone = c.prev ? (c.prev.entities || []).filter((e) => e.place === placeId && !here.some((h) => h.id === e.id)) : [];
    const force = (e, note, v) => `<div class="frow"><i style="background:${C.map.colour(run, e.owner)}"></i><span>${L(e.kind)}</span><span class="fid">${esc(e.id)}${note}</span>${v}</div>`;
    const forces = here.length || gone.length
      ? here.map((e) => {
          const was = prevE[e.id], now = Number((e.attrs || {})[size] || 0);
          const moved = was && was.place !== placeId ? ` <em>${t("arrived")} ${L(was.place)}</em>` : "";
          const v = was && was.place === placeId ? value(Number((was.attrs || {})[size] || 0), now) : `<span class="tv">${fmt(now)}</span>`;
          return force(e, moved, v);
        }).join("") + gone.map((e) => force(e, ` <em>${t("left")}</em>`, "")).join("")
      : `<div class="none">${t("no_forces")}</div>`;
    let aimed = "";
    if (c.turn) {
      const list = (c.actions || []).flatMap((dcl) => dcl.actions.filter((a) => a.place === placeId).map((a) => ({ actor: dcl.actor, a })));
      aimed = `<div class="tsec">${t("aimed_here")} ${esc(c.turn)}</div>` + (c.sealed
        ? `<div class="none">${t("still_sealed")}</div>`
        : list.length ? list.map((x) => `<div class="drow"><b style="color:${C.map.colour(run, x.actor)}">${L(x.actor)}</b> · ${L(x.a.type)}${x.a.intensity ? " ×" + esc(x.a.intensity) : ""}</div>`).join("")
        : `<div class="none">${t("nobody_aimed")}</div>`);
    }
    const when = esc(c.prev ? `${t("after")} ${c.turn}` : c.turn ? `${t("at_start")} ${c.turn}` : t("initial"));
    const holder = st.owner ? `${t("controlled_by")} ${L(st.owner)}` : t("open_water");
    return `<div class="th"><b>${L(placeId)}</b><span class="own" style="color:${st.owner ? C.map.colour(run, st.owner) : "#8a95a5"}">${holder}</span></div>
      <div class="tsub">${when}</div>${attrs}
      <div class="tsec">${t("forces_here")}</div>${forces}${aimed}
      <div class="tadj">${t("borders")}: ${(p.adjacency || []).map(L).join(", ")}${p.source ? ` · ${t("source")} <code>${esc(p.source)}</code>` : ""}</div>`;
  }

  // One card element per page, following the pointer. `refresh` re-reads what is
  // under a still pointer, because a map redrawn under it has a new context.
  let tip = null, mx = -1, my = -1, currentRun = null;
  function show(target, x, y) {
    const g = target && target.closest ? target.closest("[data-place]") : null;
    const svg = g && g.ownerSVGElement;
    const c = svg && C.map.context(svg.dataset.ctx);
    if (!c || !currentRun) { tip.style.display = "none"; tip.dataset.key = ""; return; }
    const key = svg.dataset.ctx + "/" + g.dataset.place;
    if (tip.dataset.key !== key) {
      tip.dataset.key = key;
      tip.innerHTML = html(currentRun, g.dataset.place, c);
      const st = (c.snapshot.places || {})[g.dataset.place] || {};
      tip.style.setProperty("--ac", st.owner ? C.map.colour(currentRun, st.owner) : "#8a95a5");
    }
    tip.style.display = "block";
    let left = x + 18, top = y + 14;
    if (left + tip.offsetWidth > innerWidth - 8) left = x - tip.offsetWidth - 18;
    if (top + tip.offsetHeight > innerHeight - 8) top = Math.max(8, innerHeight - tip.offsetHeight - 8);
    tip.style.left = left + "px"; tip.style.top = top + "px";
  }
  function attach(doc, run) {
    currentRun = run;
    if (tip) return;
    tip = doc.createElement("div"); tip.id = "tip"; doc.body.appendChild(tip);
    doc.addEventListener("mousemove", (e) => { mx = e.clientX; my = e.clientY; show(e.target, mx, my); });
  }
  function refresh() { if (tip && mx >= 0) show(document.elementFromPoint(mx, my), mx, my); }

  C.card = { html, attach, refresh, fmt };
})();

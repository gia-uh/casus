// The game viewer: one turn in four beats. Thinking and declaring happen in the
// war room (one pane per actor); resolving and the dispatch happen in the
// command post (the map fills the screen). Live, beats advance on a clock;
// recorded, they wait for the arrow key. `auto` and `frozen` are separate.
(function () {
  const C = (window.Casus = window.Casus || {});
  const t = (k) => C.i18n.t(k);
  const BEATS = ["thinking", "declaring", "resolving", "dispatch"];
  const HOLD = [1400, 2600, 0, 5200];     // ms a finished beat lingers when auto
  const PHASES = ["legality", "upkeep", "movement", "contest", "consequences"];

  function rng(seed) { let s = seed >>> 0; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 2 ** 32); }
  function pad2(n) { return String(n).padStart(2, "0"); }
  function rationaleFor(run, turn, actorId, declared) { return declared ? declared.rationale : ""; }

  function mount(root, run, opts) {
    const live = opts.mode === "live";
    const V = { ti: 0, beat: 0, clock: 0, last: 0, hold: 0, auto: live, frozen: false, done: false, raf: 0, panes: [], cmd: null };
    const esc = C.map.esc, L = (k) => esc(C.records.label(run, k));
    const actors = C.records.actorIds(run);
    const lang = (run.header && run.header.language) || "en";
    C.i18n.use(lang);
    C.card.attach(document, run);

    root.innerHTML = `
      <div class="visor">
        <div class="vhead">
          <div><div class="scn">${esc(run.header ? run.header.name : "")} · ${t("seed")} ${run.header ? run.header.seed : ""}</div><div class="day" id="vday"></div></div>
          <div class="beats" id="vbeats">${BEATS.map((b) => `<div class="beat">${t(b)}</div>`).join("")}</div>
          <div class="sp"></div><div class="ready" id="vready"></div>
          <div>${live ? `<span class="livetag"><span class="livedot"></span>${t("live")}</span>` : `<span class="rectag">● ${t("recorded")}</span>`}</div>
        </div>
        <div class="stage" id="stage"></div>
        <div class="controls chrome">
          <button class="iconbtn" id="bprev">◀</button><button class="iconbtn" id="bplay"></button><button class="iconbtn" id="bnext">▶</button>
          <div class="dots" id="vdots"></div><div class="sp"></div><div class="keys">${t("keys")}</div>
        </div>
      </div>`;
    const $ = (s) => root.querySelector(s);

    const turns = () => run.playable();
    const T = () => turns()[V.ti];
    function header() {
      const cur = T();
      $("#vday").innerHTML = cur ? `${t("day")} ${pad2(cur.turn)}<small>/ ${run.header ? run.header.turns : ""}</small>` : "";
      [...$("#vbeats").children].forEach((el, i) => { el.className = "beat" + (i === V.beat ? " on" : i < V.beat ? " past" : ""); });
      $("#vdots").innerHTML = turns().map((x, i) => `<div class="dot${i === V.ti ? " cur" : i < V.ti ? " done" : ""}" data-i="${i}"></div>`).join("");
      $("#bplay").textContent = V.auto ? t("auto_on") : t("auto_off");
      $("#stage").classList.toggle("frozen", V.frozen);
      $("#stage").dataset.frozen = t("frozen");
    }
    function enter(beat) {
      V.beat = beat; V.clock = 0; V.hold = 0;
      if (!T()) return;
      if (beat === 0) warRoom(); else if (beat === 1) reveal(); else if (beat === 2) commandPost(); else dispatch();
      header(); C.card.refresh();
    }

    // ---- beats 0-1: the war room ----
    function mapCtx(extra) { return Object.assign({ turn: T().turn }, extra); }
    // A run with no coordinates has no map: map.draw swaps the svg for a
    // .nomap div, so a later redraw finds nothing and must skip it.
    function paint(sel, snap, opts) { const svg = $(sel); if (svg) C.map.draw(svg, run, snap, opts); }
    function warRoom() {
      const cur = T(), r = rng(cur.turn * 7919 + 17), declared = C.records.declarations(cur);
      V.panes = actors.map((id) => {
        const d = declared.find((x) => x.actor === id) || null;
        const prompt = cur.prompts.find((p) => p.actor === id);
        return { id, d, model: prompt ? prompt.model : "", start: 500 + r() * 2600, cps: 38 + r() * 55 };
      });
      const hasLadder = !!(run.scenario.display || {}).ladder;
      $("#stage").innerHTML = `
        <div class="war">
          <div class="panes" style="grid-template-columns:repeat(${Math.max(1, V.panes.length)},1fr)">${V.panes.map((p) => `
            <div class="pane" id="pane-${esc(p.id)}" style="--ac:${C.map.colour(run, p.id)}" onclick="this.classList.toggle('open')">
              <div class="who"><b>${L(p.id)}</b><span class="model">${esc(p.model)}</span></div>
              <div class="status"></div>
              <div class="chips"><div class="sealed">${t("sealed")}</div></div>
              <div class="text"></div>
              <div class="assess">${t("expects")} <em>${esc(p.d ? p.d.assessment : "")}</em></div>
            </div>`).join("")}</div>
          <div class="board" style="grid-template-columns:${hasLadder ? "1.25fr 1fr 1.1fr" : "1.4fr 1fr"}">
            <div class="bpanel"><div class="lbl">${t("theatre")}</div><svg id="boardmap"></svg></div>
            ${hasLadder ? `<div class="bpanel"><div class="lbl">${t("ladder")}</div>${ladderHTML(cur.before)}</div>` : ""}
            <div class="bpanel"><div class="lbl">${t("standing")}</div>${standingHTML(cur.before)}</div>
          </div>
          ${cur.complete ? "" : `<div class="banner">${t("incomplete")}</div>`}
        </div>`;
      paint("#boardmap", cur.before, { font: 2.2, ctx: mapCtx({ sealed: true }) });
    }
    function ladderHTML(snap) {
      const lad = run.scenario.display.ladder, rungs = lad[lang] || lad.en || [];
      return `<div class="ladder">${actors.map((id) => {
        const rung = Math.round(Number(((snap.actors[id] || {}).resources || {})[lad.resource] || 0));
        return `<div class="lrow" style="--ac:${C.map.colour(run, id)}"><div>${L(id)}</div><div class="cells" style="grid-template-columns:repeat(${rungs.length},1fr)">${rungs.map((name, i) => `<div class="cell${i <= rung ? " on" : ""}${i === rung ? " top" : ""}" title="${esc(name)}"></div>`).join("")}</div></div>`;
      }).join("")}</div>`;
    }
    function scaleOf(k) {
      const d = run.scenario.display || {};
      const max = ((run.scenario.resources || {})[k] || {}).max;
      if ((d.scale || {})[k]) return Number(d.scale[k]);
      if (typeof max === "number") return max;
      const first = turns()[0];
      return Math.max(1, ...actors.map((id) => Number((((first.before.actors[id] || {}).resources) || {})[k] || 0))) * 1.2;
    }
    function standingHTML(snap) {
      const keys = (run.scenario.display || {}).standing || [];
      return `<div class="stand"><div class="shead" style="grid-template-columns:62px repeat(${keys.length},1fr)"><div></div>${keys.map((k) => `<div>${L(k)}</div>`).join("")}</div>
        ${actors.map((id) => `<div class="srow" style="--ac:${C.map.colour(run, id)};grid-template-columns:62px repeat(${keys.length},1fr)"><div>${L(id)}</div>${keys.map((k) => {
          const v = Number((((snap.actors[id] || {}).resources) || {})[k] || 0);
          return `<div class="bar" title="${L(k)}: ${C.card.fmt(v)}"><i style="width:${Math.min(100, (v / scaleOf(k)) * 100)}%"></i></div>`;
        }).join("")}</div>`).join("")}</div>`;
    }
    function paneFrame() {
      let done = 0;
      for (const p of V.panes) {
        const el = document.getElementById("pane-" + p.id); if (!el) continue;
        const txt = rationaleFor(run, T().turn, p.id, p.d) || "";
        const n = V.clock < p.start ? 0 : Math.min(txt.length, Math.floor(((V.clock - p.start) / 1000) * p.cps));
        const st = el.querySelector(".status");
        const finished = p.d && n >= txt.length;
        if (!p.d && !live) { st.textContent = "—"; done++; continue; }
        if (V.clock < p.start || (!txt.length && !p.d)) { st.textContent = t("thinking") + ".".repeat(1 + (Math.floor(V.clock / 400) % 3)); st.className = "status"; el.classList.remove("writing"); }
        else if (!finished) { st.textContent = t("writing"); st.className = "status"; el.classList.add("writing"); }
        else { st.textContent = "✓ " + t("ready"); st.className = "status done"; el.classList.remove("writing"); done++; }
        const tx = el.querySelector(".text");
        tx.innerHTML = esc(txt.slice(0, n)) + (n > 0 && n < txt.length ? '<span class="cur"></span>' : "");
        tx.scrollTop = tx.scrollHeight;
      }
      $("#vready").innerHTML = `<b>${pad2(done)}</b> / ${pad2(V.panes.length)} ${t("ready_count")}`;
      return done === V.panes.length;
    }
    function reveal() {
      for (const p of V.panes) {
        const el = document.getElementById("pane-" + p.id); if (!el || !p.d) continue;
        el.classList.add("revealed");
        el.querySelector(".chips").innerHTML = p.d.actions.map((a, i) => `<div class="chip" style="animation-delay:${actors.indexOf(p.id) * 0.12 + i * 0.08}s">${L(a.type)}${a.place ? `<span class="tgt">▸ ${L(a.place)}</span>` : a.target ? `<span class="tgt">▸ ${L(a.target)}</span>` : ""}<span class="int">${a.intensity ? "×" + a.intensity : ""}</span></div>`).join("");
      }
      const declared = C.records.declarations(T());
      const targets = declared.flatMap((d) => d.actions.filter((a) => a.place).map((a) => ({ actor: d.actor, place: a.place })));
      paint("#boardmap", T().before, { targets, font: 2.2, ctx: mapCtx({ actions: declared }) });
      $("#vready").innerHTML = `<b>${pad2(declared.length)}</b> / ${pad2(V.panes.length)} ${t("declared_count")}`;
    }

    // ---- beats 2-3: the command post ----
    function deltas(cur) {
      const out = [], keys = (run.scenario.display || {}).standing || [];
      const worse = new Set((run.scenario.display || {}).worse_when_higher || []);
      if (!cur.after) return out;
      for (const id of actors) for (const k of keys) {
        const a = Number(((cur.before.actors[id] || {}).resources || {})[k] || 0);
        const b = Number(((cur.after.actors[id] || {}).resources || {})[k] || 0);
        if (Math.abs(b - a) >= 0.5) out.push({ ac: C.map.colour(run, id), what: `${L(k)} · ${L(id)}`, a, b, w: Math.abs(b - a) / Math.max(1, scaleOf(k) / 10) });
      }
      for (const [pid, p] of Object.entries(cur.after.places || {})) for (const k of (run.scenario.display || {}).card || []) {
        const a = Number(((cur.before.places[pid] || {}).attrs || {})[k] || 0), b = Number((p.attrs || {})[k] || 0);
        if (Math.abs(b - a) >= 0.5) out.push({ ac: "#ff8a9b", what: `${L(k)} · ${L(pid)}`, a, b, worse: worse.has(k), w: Math.abs(b - a) / 8 });
      }
      return out.sort((x, y) => y.w - x.w).slice(0, 6);
    }
    // The five phases are the engine's, so their names are chrome; a scenario
    // may still rename one through display.labels.
    function phaseLabel(p) {
      const own = (((run.scenario.display || {}).labels || {})[lang] || {})[p];
      return esc(own ? String(own) : t(p));
    }
    function aspect() { const s = $("#stage"); return s ? s.clientWidth / Math.max(300, s.clientHeight) : 2; }
    function commandPost() {
      const cur = T(), declared = C.records.declarations(cur);
      const targets = declared.flatMap((d) => d.actions.filter((a) => a.place).map((a) => ({ actor: d.actor, place: a.place })));
      V.cmd = { deltas: deltas(cur), shown: 0, events: cur.events, swapped: false };
      $("#stage").innerHTML = `
        <div class="cmd">
          <div class="bigmap"><svg id="bigmap"></svg></div><div class="vign"></div>
          <div class="phases" id="phases">${PHASES.map((p) => `<div class="phase">${phaseLabel(p)}</div>`).join("")}<div class="ledger" id="ledger"></div></div>
          <div class="deltas" id="deltas"></div>
          <div class="hud" style="grid-template-columns:repeat(${Math.max(1, actors.length)},1fr)">${actors.map((id) => { const d = declared.find((x) => x.actor === id); return `<div class="hudc" style="--ac:${C.map.colour(run, id)}"><b>${L(id)}</b>${d ? d.actions.map((a) => `<div class="a">${L(a.type)}${a.place ? " ▸ " + L(a.place) : ""}</div>`).join("") : ""}</div>`; }).join("")}</div>
          ${cur.complete ? "" : `<div class="banner">${t("incomplete")}</div>`}
          ${run.error && run.error.turn === cur.turn ? `<div class="banner">${t("failed")} ${esc(run.error.error)}</div>` : ""}
        </div>`;
      paint("#bigmap", cur.before, { targets, aspect: aspect(), slice: true, font: 1.25, edges: true, rscale: 0.5, ctx: mapCtx({ actions: declared }) });
      $("#vready").innerHTML = `<b>${cur.mutations}</b> ${t("mutations")}`;
    }
    function commandFrame() {
      const cur = T(), k = Math.floor(V.clock / 520);
      [...$("#phases").querySelectorAll(".phase")].forEach((el, i) => { el.className = "phase" + (i === k ? " on" : i < k ? " past" : ""); });
      if (k >= PHASES.length && !V.cmd.swapped) {
        V.cmd.swapped = true;
        $("#ledger").textContent = `${cur.mutations} ${t("ledger")}`;
        if (cur.after) {
          paint("#bigmap", cur.after, { aspect: aspect(), slice: true, font: 1.25, edges: true, rscale: 0.5,
            ctx: mapCtx({ prev: cur.before, actions: C.records.declarations(cur) }) });
          setTimeout(C.card.refresh);
        }
      }
      const total = V.cmd.events.length + V.cmd.deltas.length;
      const want = k < PHASES.length ? 0 : Math.min(total, Math.floor((V.clock - 2600) / 380) + 1);
      const box = $("#deltas");
      while (V.cmd.shown < want) {
        const i = V.cmd.shown++;
        if (i < V.cmd.events.length) {
          const e = V.cmd.events[i];
          box.insertAdjacentHTML("beforeend", `<div class="evt"><b>${L(e.id)}</b>${esc((e.detail || {}).reason || "")}</div>`);
        } else {
          const d = V.cmd.deltas[i - V.cmd.events.length];
          box.insertAdjacentHTML("beforeend", `<div class="delta" style="--ac:${d.ac}"><span class="what">${d.what}</span><span class="num ${(d.b < d.a) !== !!d.worse ? "down" : "up"}" data-a="${d.a}" data-b="${d.b}" data-t="${V.clock}">${C.card.fmt(d.a)}</span></div>`);
        }
      }
      box.querySelectorAll(".num").forEach((el) => {
        const a = +el.dataset.a, b = +el.dataset.b, f = Math.min(1, (V.clock - +el.dataset.t) / 1200);
        el.textContent = f < 1 ? C.card.fmt(a + (b - a) * (1 - Math.pow(1 - f, 3))) : `${C.card.fmt(a)} → ${C.card.fmt(b)}`;
      });
      return k >= PHASES.length && V.cmd.shown >= total && V.clock > 2600 + want * 380 + 1400;
    }
    function dispatch() {
      const cur = T(), declared = C.records.declarations(cur);
      const lines = declared.map((d) => `<li><b>${L(d.actor)}</b>: ${d.actions.map((a) => L(a.type) + (a.place ? " · " + L(a.place) : "")).join(", ")}</li>`).join("");
      $("#stage").insertAdjacentHTML("beforeend", `
        <div class="dispatch" id="dispatch">
          <div class="kick"><span>${t("dispatch_of")} ${cur.turn}</span><span>${esc(run.header ? run.header.name : "")}</span></div>
          <h2>${esc(cur.narrative || t("no_dispatch"))}</h2><ul>${lines}</ul>
        </div>`);
    }
    // How the run closes: an error ends it wherever it happened, even before a
    // turn anybody could play; a run with neither error nor end was cut short.
    function closing() {
      const why = run.error ? t("failed") : run.ended ? t("end") : t("incomplete");
      return `<div class="finale"><div class="box"><div class="rectag">${why}</div><h2>${esc(run.header ? run.header.name : "")}</h2>${run.error ? `<p>${esc(run.error.error)}</p>` : ""}</div></div>`;
    }
    function finale() { $("#stage").insertAdjacentHTML("beforeend", closing()); }
    // A recorded run with no playable turn has nothing to step through; say why.
    // A live one is still waiting unless it has already failed.
    function empty() { $("#stage").innerHTML = !live || run.error ? closing() : ""; header(); }

    // ---- the clock and the keys ----
    function next() {
      if (V.done || !T()) return;
      if (V.beat === 0) { if (!paneFrame() && !live) { V.clock = 1e9; paneFrame(); return; } enter(1); }
      else if (V.beat < 3) enter(V.beat + 1);
      else if (V.ti < turns().length - 1) { V.ti++; enter(0); }
      else if (!live || run.ended) { V.done = true; finale(); }
    }
    function prev() {
      if (V.done) { V.done = false; const f = root.querySelector(".finale"); if (f) f.remove(); return; }
      if (V.beat === 0) { if (V.ti > 0) { V.ti--; enter(0); V.clock = 1e9; } }
      else if (V.beat === 1) { enter(0); V.clock = 1e9; }
      else if (V.beat === 2) { enter(0); V.clock = 1e9; paneFrame(); enter(1); }
      else { const d = $("#dispatch"); if (d) d.remove(); V.beat = 2; header(); }
    }
    function frame(ts) {
      const dt = V.last ? ts - V.last : 0; V.last = ts;
      if (!V.frozen && !V.done) V.clock += dt;
      if (!V.done && T()) {
        let finished;
        if (V.beat === 0) finished = paneFrame();
        else if (V.beat === 1) finished = V.clock > 900;
        else if (V.beat === 2) finished = commandFrame();
        else finished = true;
        if (finished && V.auto && !V.frozen) { V.hold += dt; if (V.hold > HOLD[V.beat]) next(); }
        else if (!finished) V.hold = 0;
      }
      V.raf = requestAnimationFrame(frame);
    }
    function key(e) {
      if (/INPUT|TEXTAREA/.test(e.target.tagName)) return;
      if (e.key === "ArrowRight") { e.preventDefault(); V.hold = 0; next(); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); prev(); }
      else if (e.key === " ") { e.preventDefault(); V.frozen = !V.frozen; header(); }
      else if (e.key === "p" || e.key === "P") document.body.classList.toggle("present");
      else if (e.key === "Escape") document.body.classList.remove("present");
    }
    document.addEventListener("keydown", key);
    $("#bnext").onclick = next; $("#bprev").onclick = prev;
    $("#bplay").onclick = () => { V.auto = !V.auto; header(); };
    $("#vdots").onclick = (e) => { const i = e.target.dataset.i; if (i !== undefined) { V.done = false; V.ti = +i; enter(0); } };

    // A live run may start with no playable turn; enter the first when it appears.
    const onChange = () => { if (V.beat === 0 && !V.panes.length) { if (T()) enter(0); else empty(); } else header(); };
    run.onChange(onChange);
    if (T()) enter(0); else empty();
    V.raf = requestAnimationFrame(frame);
    return {
      destroy() { cancelAnimationFrame(V.raf); document.removeEventListener("keydown", key); },
      state() { return { turn: T() ? T().turn : null, beat: V.beat, auto: V.auto, frozen: V.frozen, done: V.done }; },
    };
  }

  C.viewer = { mount, rationaleFor, BEATS };
})();

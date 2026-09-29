// The app shell: a home with two shelves, and hash routes that fill the screen.
// Later slices register more routes with Casus.shell.route(name, fn).
(function () {
  const C = (window.Casus = window.Casus || {});
  const routes = {};
  let current = null;
  const esc = (s) => C.map.esc(s);
  const view = () => document.getElementById("view");

  async function json(url) { const r = await fetch(url); if (!r.ok) throw new Error(url + " " + r.status); return r.json(); }

  function route(name, fn) { routes[name] = fn; }

  async function home() {
    const [scenarios, runs] = await Promise.all([json("/api/scenarios"), json("/api/runs")]);
    const byScenario = {};
    for (const r of runs) (byScenario[r.scenario] = byScenario[r.scenario] || []).push(r);
    view().innerHTML = `
      <div class="home">
        <div class="hero"><h1>cas<i>us</i></h1></div>
        <section class="shelf"><h2>${C.i18n.t("scenarios")}</h2><div class="row">${scenarios.map((s) => `
          <div class="card" data-scenario="${esc(s.dir)}"><h3>${esc(s.name)}</h3>
            <div class="meta">${s.actors ?? "?"} · ${s.places ?? "?"} · ${s.turns ?? "?"}</div><p>${esc(s.description || "")}</p>
            <div class="acts"><span class="badge ${s.valid ? "ok" : "bad"}">${s.valid ? "✓" : "✗ " + esc(s.findings[0] || "")}</span></div>
            <div class="acts" data-actions="scenario"></div></div>`).join("")}</div></section>
        <section class="shelf"><h2>${C.i18n.t("studies")}</h2><div class="row">${Object.entries(byScenario).map(([name, rs]) => `
          <div class="card" data-study="${esc(name)}"><h3>${esc(name)} <span class="meta">· ${rs.length}</span></h3>
            <div class="runlist">${rs.map((r) => `<div class="runrow"><div class="meta">${esc(r.id)}<br>${r.turns_done}/${r.turns_planned} · ${esc(r.status)}</div>
              <button class="btn small" data-run="${esc(r.id)}">${C.i18n.t("view")} ▸</button></div>`).join("")}</div>
            <div class="acts" data-actions="study"></div></div>`).join("")}</div></section>
      </div>`;
    for (const fn of hooks.home) fn(view());
  }

  async function viewRun(id) {
    const records = await json("/api/runs/" + encodeURIComponent(id));
    const run = new C.records.RunModel();
    for (const r of records) run.push(r);
    view().innerHTML = "";
    const handle = C.viewer.mount(view(), run, { mode: "recorded" });
    return () => handle.destroy();
  }

  const hooks = { home: [] };
  function onHome(fn) { hooks.home.push(fn); }

  async function dispatch() {
    if (current) { current(); current = null; }
    document.body.classList.remove("present");
    const [, name, ...parts] = (location.hash || "#/").split("/");
    const args = parts.map(decodeURIComponent);
    document.getElementById("crumbs").textContent = name ? `› ${name} · ${args.join(" · ")}` : "";
    // A route gets every path segment after its name: #/study/<scenario>/<version> has two.
    if (name === "view") current = await viewRun(args[0]);
    else if (routes[name]) current = await routes[name](view(), ...args);
    else await home();
  }

  function start() {
    window.addEventListener("hashchange", dispatch);
    // One delegated listener, so a run id never lands inside inline script.
    view().addEventListener("click", (e) => {
      const button = e.target.closest("[data-run]");
      if (button) location.hash = "#/view/" + encodeURIComponent(button.dataset.run);
    });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !document.body.classList.contains("present")) location.hash = "#/"; });
    dispatch();
  }

  C.shell = { start, route, onHome, json };
})();

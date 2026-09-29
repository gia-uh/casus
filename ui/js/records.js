// Folds transcript records into turns. State N is the world before turn N
// resolves, so turn N's `after` is state N+1 and a turn is complete when that
// state exists. Records may arrive all at once (a bundle) or one by one (live).
(function () {
  const C = (window.Casus = window.Casus || {});

  function emptyTurn(n) {
    return { turn: n, before: null, after: null, prompts: [], actions: [], events: [],
             narrative: "", mutations: 0, complete: false };
  }

  class RunModel {
    constructor() {
      this.header = null; this.scenario = {}; this.turns = []; this.deltas = {};
      this.error = null; this.ended = false; this._fns = [];
    }
    onChange(fn) { this._fns.push(fn); }
    turn(n) { return this.turns.find((t) => t.turn === n) || null; }
    _ensure(n) {
      let t = this.turn(n);
      if (!t) { t = emptyTurn(n); this.turns.push(t); this.turns.sort((a, b) => a.turn - b.turn); }
      return t;
    }
    push(r) {
      switch (r.kind) {
        case "scenario": this.header = r; this.scenario = r.scenario || {}; break;
        case "state": {
          this._ensure(r.turn).before = r.state;
          const prev = this.turn(r.turn - 1);
          if (prev) { prev.after = r.state; prev.complete = true; }
          break;
        }
        case "prompt": this._ensure(r.turn).prompts.push(r); break;
        case "action": this._ensure(r.turn).actions.push(r); break;
        case "event": this._ensure(r.turn).events.push(r.event); break;
        case "ledger": this._ensure(r.turn).mutations = r.mutations; break;
        case "mutation": this._ensure(r.turn).mutations += 1; break;
        case "narrative": this._ensure(r.turn).narrative = r.text || ""; break;
        case "delta": {
          const byActor = (this.deltas[r.turn] = this.deltas[r.turn] || {});
          (byActor[r.actor] = byActor[r.actor] || []).push(r.text);
          break;
        }
        case "error": this.error = r; break;
        case "end": this.ended = true; break;
        default: return;
      }
      for (const fn of this._fns) fn(r.kind, this, r);
    }
    // Turns somebody was asked about. The last state opens a turn nobody plays.
    playable() { return this.turns.filter((t) => t.prompts.length || t.actions.length); }
  }

  function actorIds(run) { return Object.keys(run.scenario.actors || {}).sort(); }

  function label(run, key) {
    const d = run.scenario.display || {};
    const lang = (run.header && run.header.language) || run.scenario.language || "en";
    const labels = (d.labels || {})[lang] || {};
    if (labels[key]) return String(labels[key]);
    const a = (run.scenario.actors || {})[key];
    if (a && a.name) return String(a.name);
    const p = (run.scenario.places || {})[key];
    if (p && p.name) return String(p.name);
    return String(key).replace(/_/g, " ");
  }

  // One entry per actor that declared, in actor order: its actions, and the
  // rationale and assessment the action records all repeat.
  function declarations(turn) {
    const by = {};
    for (const r of turn.actions) {
      const d = (by[r.actor] = by[r.actor] || { actor: r.actor, actions: [], rationale: "", assessment: "" });
      d.actions.push(r.action);
      d.rationale = d.rationale || r.rationale || "";
      d.assessment = d.assessment || r.assessment || "";
    }
    return Object.keys(by).sort().map((k) => by[k]);
  }

  C.records = { RunModel, actorIds, label, declarations };
})();

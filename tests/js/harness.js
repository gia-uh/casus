// Loads ui/js scripts into one context with a fake window, then runs the test
// named on the command line. Prints JSON; exits 1 on a failed assertion.
const fs = require("fs");
const vm = require("vm");
const path = require("path");
const root = path.join(__dirname, "..", "..", "ui", "js");
const ctx = { window: {}, console };
ctx.window.window = ctx.window;
vm.createContext(ctx);
for (const name of process.argv[2].split(",")) {
  vm.runInContext(fs.readFileSync(path.join(root, name), "utf8"), ctx, { filename: name });
}
const input = JSON.parse(fs.readFileSync(0, "utf8"));
const Casus = ctx.window.Casus;
const run = new Casus.records.RunModel();
for (const r of input.records) run.push(r);
const out = {
  scenario: run.header && run.header.name,
  playable: run.playable().map((t) => t.turn),
  complete: run.playable().map((t) => t.complete),
  mutations: run.playable().map((t) => t.mutations),
  actors: Casus.records.actorIds(run),
  labels: input.labels.map((k) => Casus.records.label(run, k)),
  declared: run.playable().map((t) => Casus.records.declarations(t).map((d) => d.actor)),
  error: run.error && run.error.error,
  ended: run.ended,
};
if (input.card) {
  const t = run.playable()[0];
  out.card = Casus.card.html(run, input.card, {
    snapshot: t.after || t.before, prev: t.after ? t.before : null, turn: t.turn,
    actions: Casus.records.declarations(t), sealed: !!input.sealed,
  });
}
process.stdout.write(JSON.stringify(out));

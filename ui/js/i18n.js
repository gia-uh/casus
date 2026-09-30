// Chrome strings. Domain words never live here: they come from the scenario's
// display.labels, through Casus.records.label.
(function () {
  const C = (window.Casus = window.Casus || {});
  const STRINGS = {
    en: {
      thinking: "thinking", declaring: "declaring", resolving: "resolving", dispatch: "dispatch",
      writing: "writing…", ready: "declaration ready", sealed: "DECLARATION SEALED",
      ready_count: "ready", declared_count: "declared", mutations: "mutations",
      ledger: "mutations in the ledger", day: "DAY", live: "LIVE", recorded: "RECORDED",
      frozen: "FROZEN", auto_on: "❚❚ manual", auto_off: "▶ advance on its own",
      keys: "→ next beat · ← previous · space freeze · P present · Esc leave",
      theatre: "Theatre", aimed: "Theatre · declared targets", ladder: "Ladder · highest rung",
      standing: "Standing", expects: "Expects of the other side:", dispatch_of: "Dispatch of day",
      no_dispatch: "No dispatch this day.", incomplete: "This turn did not finish.",
      failed: "The run stopped here:", end: "END", home: "Home", scenarios: "Scenarios",
      studies: "Runs", view: "View", no_map: "no map for this scenario",
      at_start: "at the start of day", after: "after resolving day", initial: "initial state",
      forces_here: "Forces here", no_forces: "no forces here", aimed_here: "Declared against this place · day",
      nobody_aimed: "nobody declared anything against this place",
      still_sealed: "the declarations are still sealed", borders: "Borders", source: "source",
      controlled_by: "held by", open_water: "nobody holds it", arrived: "arrived from", left: "left",
      seed: "seed", legality: "legality", upkeep: "upkeep", movement: "movement", contest: "contest",
      consequences: "consequences", cannot_open: "This could not be opened.", no_run_id: "no run was named",
    },
    es: {
      thinking: "pensando", declaring: "declarando", resolving: "resolviendo", dispatch: "parte",
      writing: "escribiendo…", ready: "declaración lista", sealed: "DECLARACIÓN SELLADA",
      ready_count: "listos", declared_count: "declarados", mutations: "mutaciones",
      ledger: "mutaciones en el libro mayor", day: "DÍA", live: "EN VIVO", recorded: "GRABADA",
      frozen: "CONGELADO", auto_on: "❚❚ manual", auto_off: "▶ avanzar solo",
      keys: "→ siguiente compás · ← anterior · espacio congelar · P presentar · Esc salir",
      theatre: "Teatro", aimed: "Teatro · objetivos declarados", ladder: "Escalera · peldaño más alto",
      standing: "Situación", expects: "Espera del rival:", dispatch_of: "Parte del día",
      no_dispatch: "Sin parte este día.", incomplete: "Este turno no terminó.",
      failed: "La corrida se detuvo aquí:", end: "FIN", home: "Inicio", scenarios: "Escenarios",
      studies: "Partidas", view: "Ver", no_map: "este escenario no tiene mapa",
      at_start: "al empezar el día", after: "tras resolver el día", initial: "estado inicial",
      forces_here: "Fuerzas aquí", no_forces: "ninguna fuerza aquí", aimed_here: "Declarado para aquí · día",
      nobody_aimed: "nadie declaró nada contra este lugar",
      still_sealed: "las declaraciones siguen selladas", borders: "Linda con", source: "fuente",
      controlled_by: "controla", open_water: "nadie la controla", arrived: "llega de", left: "se fue",
      seed: "semilla", legality: "legalidad", upkeep: "mantenimiento", movement: "movimiento", contest: "disputa",
      consequences: "consecuencias", cannot_open: "No se pudo abrir.", no_run_id: "no se indicó ninguna partida",
    },
  };
  let lang = "en";
  C.i18n = {
    use(l) { lang = STRINGS[l] ? l : "en"; },
    lang() { return lang; },
    t(key) { return (STRINGS[lang] && STRINGS[lang][key]) || STRINGS.en[key] || key; },
  };
})();

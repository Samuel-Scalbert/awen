/* Séance : la carte des exercices, un exercice ouvert à la fois, la saisie.
 *
 * Tout ce qu'il faut savoir d'un exercice arrive dans data-card. Les charges
 * sont en kilos, et la charge avance d'un cran de la machine à la fois
 * (stepkg : 4,5359 kg pour une pile graduée en livres par crans de 10) : le
 * script ne propose jamais une charge qui n'existe pas sur la pile.
 *
 * Rien ne bouge sans un geste. La page ne défile pas et ne change pas
 * d'exercice toute seule : un téléphone reposé entre deux séries doit
 * retrouver l'écran qu'il a quitté.
 */
(function () {
  "use strict";

  const root = document.getElementById("seance");
  if (!root) return;
  const R = root.dataset;
  const MODE = R.mode;
  const KEY = "awen-seance-" + R.workout;
  const REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------- état persistant (survit à la sortie de l'appli) ---------- */
  function load() {
    try { return JSON.parse(localStorage.getItem(KEY)) || {}; }
    catch (e) { return {}; }
  }
  function save(patch) {
    const st = Object.assign(load(), patch);
    try { localStorage.setItem(KEY, JSON.stringify(st)); } catch (e) { /* mode privé */ }
    return st;
  }
  function remember(map, id, value) {
    const st = load();
    st[map] = st[map] || {};
    if (value === null) delete st[map][id]; else st[map][id] = value;
    save(st);
  }

  const num = (v) => String(Math.round((+v || 0) * 100) / 100).replace(".", ",");
  const read = (input) => parseFloat(String(input.value).replace(",", ".")) || 0;
  const plural = (n, word) => n + " " + word + (Math.abs(n) > 1 ? "s" : "");

  /* ---------- les crans de la machine ---------- */
  // Au dixième de kilo sur une pile en livres (31,8), au centième sinon.
  const tidy = (d, v) => {
    const k = d.grid === "lb" ? 10 : 100;
    return Math.max(0, Math.round(v * k) / k);
  };
  // n crans au-dessus (ou au-dessous) de la charge v, sur la grille exacte :
  // partir d'un arrondi à chaque appui finirait par décaler les charges.
  const notch = (d, v, n) => tidy(d, (Math.round(v / d.stepkg) + n) * d.stepkg);
  // Même cran : 32 kg saisis de tête avant et 31,8 kg (70 lb) aujourd'hui.
  const sameLoad = (d, a, b) => Math.abs(a - b) < d.stepkg / 2;

  /* ---------- les exercices ---------- */
  const cards = [];
  document.querySelectorAll(".exo-panel").forEach((panel) => {
    const data = JSON.parse(panel.dataset.card);
    cards.push({
      id: String(data.id),
      data,
      panel,
      tile: document.querySelector('.exo-tile[data-exo="' + data.id + '"]'),
      form: panel.querySelector(".set-form"),
      list: panel.querySelector(".sets-table"),
      advice: panel.querySelector(".set-advice"),
      fini: panel.querySelector(".exo-fini"),
    });
  });
  const byId = (id) => cards.find((c) => c.id === String(id));
  const empty = document.getElementById("exo-empty");

  /* ---------- une série, en texte ---------- */
  function setText(d, s, withUnit) {
    if (d.kind === "sec") return s.reps + " s";
    if (!d.loaded || !s.v) return plural(s.reps, "rep");
    return s.reps + " × " + num(s.v) + (withUnit ? " kg" : "");
  }

  /* Ce qui a changé depuis la dernière fois, série par série. La charge
     passe avant les reps : après une montée de charge, perdre deux reps est
     attendu, et c'est bien une progression. Sur une machine d'assistance,
     moins d'assistance veut dire plus fort. */
  function delta(d, now, before) {
    if (!now || !before) return null;
    if (d.loaded && !sameLoad(d, now.v, before.v)) {
      const diff = now.v - before.v;
      const better = d.assist ? diff < 0 : diff > 0;
      return { cls: better ? "up" : "down",
               txt: (diff > 0 ? "+" : "−") + num(Math.round(Math.abs(diff) * 10) / 10) + " kg" };
    }
    const r = now.reps - before.reps;
    if (r === 0) return { cls: "same", txt: "=" };
    return { cls: r > 0 ? "up" : "down",
             txt: (r > 0 ? "+" : "−") + Math.abs(r) + (d.kind === "sec" ? " s" : " reps") };
  }

  function render(c) {
    const d = c.data;
    const total = Math.max(d.sets, d.done.length);
    const rows = ['<li class="sets-head"><span></span><span>Dernière fois</span>'
      + '<span>Aujourd\'hui</span><span></span></li>'];
    for (let i = 0; i < total; i++) {
      const now = d.done[i], before = d.prev[i];
      const prevTxt = before ? setText(d, before, false) : "";
      if (now) {
        const dl = delta(d, now, before);
        rows.push('<li class="set-done" data-set="' + now.id + '">'
          + '<span class="set-n">' + (i + 1) + '</span>'
          + '<span class="set-prev">' + prevTxt + '</span>'
          + '<span class="set-now">' + setText(d, now, true) + '</span>'
          + '<span class="set-end">'
          + (dl ? '<span class="set-delta ' + dl.cls + '">' + dl.txt + '</span>' : "")
          + '<button type="button" class="del" aria-label="Supprimer la série ' + (i + 1) + '">✕</button>'
          + '</span></li>');
      } else {
        const next = i === d.done.length;
        rows.push('<li class="' + (next ? "set-next" : "set-todo") + '">'
          + '<span class="set-n">' + (i + 1) + '</span>'
          + '<span class="set-prev">' + prevTxt + '</span>'
          + '<span class="set-now">' + (next ? "à faire" : "") + '</span>'
          + '<span class="set-end"></span></li>');
      }
    }
    c.list.innerHTML = rows.join("");

    // Au-dessus de la saisie : quelle série, et ce qu'il y avait à battre.
    const n = d.done.length;
    const before = d.prev[n];
    let cue = n < d.sets ? "Série " + (n + 1) + " sur " + d.sets
                         : "Série en plus (" + (n + 1) + ")";
    if (before) cue += ". La dernière fois : " + setText(d, before, true);
    c.panel.querySelector(".set-cue").textContent = cue;

    const done = d.done.length >= d.sets;
    c.fini.hidden = !done;
    if (done) {
      const next = nextAfter(c);
      const btn = c.fini.querySelector(".exo-next");
      btn.hidden = !next;
      if (next) {
        btn.textContent = "Passer à : " + next.data.name;
        btn.onclick = () => select(next.id, true);
      }
    }
  }

  /* L'exercice suivant non terminé, dans l'ordre du programme. Seulement
     proposé : c'est la machine libre qui décide. En reprise et en plyo, il
     n'y a pas d'ordre à suggérer. */
  function nextAfter(c) {
    if (MODE !== "force") return null;
    const i = cards.indexOf(c);
    for (let k = 1; k < cards.length; k++) {
      const other = cards[(i + k) % cards.length];
      if (other.data.done.length < other.data.sets) return other;
    }
    return null;
  }

  /* ---------- la carte et l'en-tête ---------- */
  function refresh() {
    let done = 0, planned = 0, logged = 0;
    cards.forEach((c) => {
      const d = c.data, n = d.done.length;
      done += Math.min(n, d.sets);
      planned += d.sets;
      logged += n;
      const pips = [];
      for (let i = 0; i < Math.max(d.sets, n); i++) pips.push(i < n ? '<i class="on"></i>' : "<i></i>");
      c.tile.querySelector(".exo-tile-pips").innerHTML = pips.join("");
      c.tile.classList.toggle("is-started", n > 0 && n < d.sets);
      c.tile.classList.toggle("is-done", n >= d.sets);
    });
    const count = document.getElementById("seance-count");
    const bar = document.getElementById("seance-bar");
    if (MODE === "force") {
      count.textContent = done + " / " + planned + " séries";
    } else {
      count.textContent = logged ? plural(logged, "série") + (logged > 1 ? " notées" : " notée")
                                 : "Aucune série notée";
    }
    if (bar) bar.style.width = (planned ? Math.round(100 * done / planned) : 0) + "%";
  }

  function select(id, scroll) {
    let shown = null;
    cards.forEach((c) => {
      const on = c.id === id;
      c.panel.hidden = !on;
      c.tile.setAttribute("aria-pressed", on ? "true" : "false");
      if (on) shown = c;
    });
    if (empty) empty.hidden = !!shown;
    save({ focus: shown ? shown.id : null });
    if (shown && scroll) {
      const top = shown.panel.getBoundingClientRect().top;
      if (top < 0 || top > window.innerHeight * 0.55) {
        shown.panel.scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "start" });
      }
    }
  }

  cards.forEach((c) => c.tile.addEventListener("click", () => select(c.id, true)));

  /* ---------- la saisie ---------- */
  function updateLabel(c) {
    const f = c.form, d = c.data;
    const reps = Math.max(0, Math.round(read(f.elements.reps)));
    let t = d.kind === "sec" ? reps + " s" : plural(reps, "rep");
    if (d.loaded) {
      const w = read(f.elements.weight);
      if (w > 0) t += " × " + num(w) + " kg";
    }
    f.querySelector(".set-submit").textContent = "Valider " + t;
  }

  /* Les reps proposées pour la série suivante, à la même charge : celles de
     la série qu'on vient de faire, sinon celles de la même série la dernière
     fois. Faute de repère, le bas de la fourchette, où l'on repart après une
     montée de charge. */
  function prefillReps(c) {
    const d = c.data, f = c.form;
    const same = (s) => s && (!d.loaded || sameLoad(d, s.v, read(f.elements.weight)));
    const last = d.done[d.done.length - 1];
    const before = d.prev[d.done.length];
    let reps;
    if (d.kind === "sec") reps = d.repmax;
    else if (same(last)) reps = last.reps;
    else if (same(before)) reps = before.reps;
    else reps = d.repmin || d.repmax || 0;
    f.elements.reps.value = reps;
    updateLabel(c);
  }

  function setWeight(c, v) {
    const w = c.form.elements.weight;
    if (!w) return;
    w.value = tidy(c.data, v);
    remember("weights", c.id, w.value);
    updateLabel(c);
  }

  cards.forEach((c) => {
    const f = c.form, d = c.data;

    f.querySelectorAll(".stepper").forEach((s) => {
      const input = s.querySelector("input");
      const field = s.dataset.field;
      const step = field === "sec" ? 5 : 1;
      s.querySelectorAll(".stepper-btn").forEach((b) => b.addEventListener("click", () => {
        const n = +b.dataset.delta;
        input.value = field === "weight" ? notch(d, read(input), n)
                                         : Math.max(0, read(input) + step * n);
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }));
      input.addEventListener("input", () => {
        if (field === "weight") remember("weights", c.id, input.value);
        updateLabel(c);
      });
    });

    /* Reps en réserve : un deuxième tap sur le même bouton le désélectionne. */
    f.querySelectorAll(".rir-pick button").forEach((btn) => btn.addEventListener("click", () => {
      const already = btn.classList.contains("on");
      f.querySelectorAll(".rir-pick button").forEach((b) => b.classList.remove("on"));
      btn.classList.toggle("on", !already);
      f.elements.rir.value = already ? "" : btn.dataset.rir;
    }));

    f.addEventListener("submit", (e) => { e.preventDefault(); logSet(c); });

    holdTimer(c);
  });

  /* ---------- messages du coach (variés, ton adapté à la série) ---------- */
  const MSG = {
    fix: [
      "On corrige tout de suite : {w} sur la prochaine, la technique avant l'ego.",
      "Trop lourd pour aujourd'hui. {w} sur la prochaine, exécution propre.",
      "On ajuste : {w}. Mieux vaut 10 reps propres que 4 arrachées.",
    ],
    low: [
      "Sous la fourchette ({min}-{max}) : {w} pour la suivante.",
      "Pas grave, on adapte : {w} sur la prochaine série.",
      "{w} pour la suivante, et tu restes dans la fourchette.",
    ],
    ok: [
      "Dans la cible. Garde {w} et vise {max} reps.",
      "Solide. Même charge, va chercher {max}.",
      "C'est la bonne charge. Prochaine série : {max} reps si tu peux.",
    ],
    top: [
      "Haut de fourchette ! Tiens {w} : toutes les séries au max, et la charge monte à la prochaine séance.",
      "{max} reps, propre. Encore les autres séries comme ça et on monte.",
      "Plafond touché. Garde {w}, la progression tombera toute seule.",
    ],
    boost: [
      "Beaucoup trop facile. On passe à {w} dès la prochaine série.",
      "{r} reps ?! La prochaine à {w}, on ne s'endort pas.",
      "Surperformance : {w} tout de suite, c'est cette difficulté qu'il te faut.",
    ],
    plain: [
      "Noté. Même chose sur la suivante si tu peux.",
      "C'est noté, continue comme ça.",
    ],
    done: [" Exercice bouclé.", " Terminé pour celui-là.", " C'est plié."],
    plyoOk: [
      "Explosif. Contact au sol le plus court possible sur la prochaine.",
      "Bien. Repos complet avant la suivante : la plyo se travaille frais.",
      "Nickel. Cherche la hauteur, pas le nombre.",
    ],
    plyoDrop: [
      "Tu perds en hauteur : récupère plus longtemps, ou arrête là.",
      "Moins que prévu : la fatigue nerveuse est arrivée, ne force pas.",
      "Qualité en baisse : mieux vaut couper la série que sauter fatigué.",
    ],
  };
  const pick = (list) => list[Math.floor(Math.random() * list.length)];
  function msg(cat, vars) {
    let t = pick(MSG[cat]);
    Object.keys(vars).forEach((k) => { t = t.split("{" + k + "}").join(vars[k]); });
    return t;
  }

  function coach(c, j) {
    // inc : la progression en crans, +1 en général, -1 sur une machine
    // d'assistance (plus dur = moins d'assistance), 0 sans progression.
    const d = c.data, rmin = d.repmin, rmax = d.repmax, inc = d.inc;
    const w = (v) => num(v) + " kg";
    let text;
    if (!d.loaded) {
      text = msg(j.reps >= rmax ? "plyoOk" : "plyoDrop", {});
    } else if (inc && j.reps <= rmin - 3) {
      const nw = notch(d, j.weight, -inc);
      text = msg("fix", { w: w(nw), min: rmin, max: rmax });
      setWeight(c, nw);
    } else if (inc && j.reps < rmin) {
      const nw = notch(d, j.weight, -inc);
      text = msg("low", { w: w(nw), min: rmin, max: rmax });
      setWeight(c, nw);
    } else if (inc && j.reps >= rmax + 3) {
      const nw = notch(d, j.weight, inc);
      text = msg("boost", { w: w(nw), r: j.reps });
      setWeight(c, nw);
    } else if (j.weight && j.reps >= rmax) {
      text = msg("top", { w: w(j.weight), max: rmax });
    } else if (j.weight) {
      text = msg("ok", { w: w(j.weight), max: rmax });
    } else {
      text = msg("plain", {});
    }
    if (d.done.length >= d.sets) text += pick(MSG.done);
    c.advice.textContent = text;
    c.advice.hidden = false;
    remember("advice", c.id, text);
  }

  /* ---------- enregistrer une série ---------- */
  async function logSet(c) {
    const f = c.form, btn = f.querySelector(".set-submit");
    btn.disabled = true;

    // Étape 1, l'enregistrement : seul ce bloc peut parler de connexion.
    let j;
    try {
      const res = await fetch(R.log, { method: "POST", body: new FormData(f) });
      if (!res.ok) throw new Error("HTTP " + res.status);
      j = await res.json();
    } catch (err) {
      alert("Série non enregistrée : vérifie la connexion, puis valide à nouveau.");
      btn.disabled = false;
      return;
    }
    btn.disabled = false;

    // Étape 2, l'affichage. La série est déjà en base : si quelque chose
    // casse ici, on le note en console sans jamais accuser le réseau (c'est
    // le bug vécu sur la plyo : un plantage d'affichage annonçait « pas de
    // connexion » et empêchait le chrono de démarrer).
    try {
      c.data.done.push({ id: j.id, v: j.weight, reps: j.reps, rir: j.rir });
      coach(c, j);
      f.elements.rir.value = "";
      f.querySelectorAll(".rir-pick button").forEach((b) => b.classList.remove("on"));
      render(c);
      refresh();
      prefillReps(c);
    } catch (err) {
      console.error("[séance] affichage après enregistrement :", err);
    }

    // Le repos démarre dans tous les cas : c'est lui qui compte.
    startTimer(+j.rest_sec || 60);
  }

  /* ---------- supprimer une série mal saisie ---------- */
  root.addEventListener("click", async (e) => {
    const btn = e.target.closest(".del");
    if (!btn) return;
    const li = btn.closest("li");
    const c = byId(btn.closest(".exo-panel").id.replace("exo-", ""));
    if (!c || !confirm("Supprimer cette série ?")) return;
    const res = await fetch(R.delete.replace("/0/", "/" + li.dataset.set + "/"), { method: "POST" });
    if (!res.ok) { alert("Suppression impossible."); return; }
    c.data.done = c.data.done.filter((s) => String(s.id) !== li.dataset.set);
    render(c);
    refresh();
    prefillReps(c);
  });

  /* ---------- séries tenues au chrono (rebonds de chevilles…) ---------- */
  // Décompte de la durée cible puis validation automatique. Un appui pendant
  // le décompte l'arrête et enregistre le temps réellement tenu.
  function holdTimer(c) {
    const btn = c.form.querySelector(".hold-timer");
    if (!btn) return;
    const input = c.form.elements.reps;
    const target = +btn.dataset.sec;
    let iv = null, endAt = 0;
    const stop = (elapsed) => {
      clearInterval(iv); iv = null;
      btn.textContent = "▶ Chrono " + target + " s";
      btn.classList.remove("running");
      input.value = Math.max(0, Math.round(elapsed));
      updateLabel(c);
    };
    btn.addEventListener("click", () => {
      if (iv) { stop(target - (endAt - Date.now()) / 1000); return; }
      endAt = Date.now() + target * 1000;
      btn.classList.add("running");
      iv = setInterval(() => {
        const left = Math.max(0, (endAt - Date.now()) / 1000);
        btn.textContent = "⏹ " + Math.ceil(left) + " s";
        if (left <= 0) { stop(target); beep(); c.form.requestSubmit(); }
      }, 100);
    });
  }

  /* ---------- chrono de repos ---------- */
  const timer = document.getElementById("timer");
  const countEl = document.getElementById("timer-count");
  let deadline = 0, iv = null;

  function beep() {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.connect(g); g.connect(ctx.destination);
      o.frequency.value = 880; g.gain.value = 0.25;
      o.start(); o.stop(ctx.currentTime + 0.5);
    } catch (e) { /* pas de son, la vibration suffit */ }
    if (navigator.vibrate) navigator.vibrate([250, 100, 250]);
  }
  function tick() {
    const left = Math.max(0, Math.round((deadline - Date.now()) / 1000));
    countEl.textContent = left + " s";
    if (left <= 0) { clearInterval(iv); timer.hidden = true; beep(); save({ deadline: 0 }); }
  }
  function startTimer(sec) {
    deadline = Date.now() + sec * 1000;
    save({ deadline });
    timer.hidden = false;
    clearInterval(iv); iv = setInterval(tick, 250); tick();
  }
  document.getElementById("timer-plus").onclick = () => { deadline += 30000; save({ deadline }); tick(); };
  document.getElementById("timer-skip").onclick = () => { deadline = Date.now(); tick(); };

  /* ---------- notes : sauvegarde automatique ---------- */
  async function saveNote(textarea, exerciseId, stateEl) {
    const body = new FormData();
    body.append("text", textarea.value);
    if (exerciseId) body.append("exercise_id", exerciseId);
    stateEl.textContent = "…";
    try {
      const res = await fetch(R.note, { method: "POST", body });
      if (!res.ok) throw new Error();
      stateEl.textContent = "enregistrée";
      stateEl.classList.remove("err");
      textarea.defaultValue = textarea.value;
      const flag = textarea.closest(".note-box") && textarea.closest(".note-box").querySelector(".note-flag");
      if (flag) flag.textContent = textarea.value.trim() ? "•" : "";
      setTimeout(() => { stateEl.textContent = ""; }, 2000);
    } catch (e) {
      stateEl.textContent = "non enregistrée, réessaie";
      stateEl.classList.add("err");
    }
  }
  // 1,2 s après la dernière frappe, et à toute sortie : à la salle on
  // verrouille souvent l'écran juste après avoir tapé.
  function autosave(textarea, exerciseId, stateEl) {
    let t = null;
    const run = () => saveNote(textarea, exerciseId, stateEl);
    textarea.addEventListener("input", () => { clearTimeout(t); t = setTimeout(run, 1200); });
    textarea.addEventListener("blur", () => { clearTimeout(t); if (textarea.value !== textarea.defaultValue) run(); });
    document.addEventListener("visibilitychange", () => {
      if (document.hidden && textarea.value !== textarea.defaultValue) { clearTimeout(t); run(); }
    });
  }
  document.querySelectorAll(".exo-note").forEach((t) =>
    autosave(t, t.dataset.exercise, t.parentElement.querySelector(".note-state")));
  const sessionNote = document.getElementById("session-note");
  if (sessionNote) autosave(sessionNote, null, document.getElementById("session-note-state"));

  /* ---------- la machine : graduation de la pile et cran ---------- */
  document.querySelectorAll(".machine-form").forEach((form) => {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const c = byId(form.closest(".exo-panel").id.replace("exo-", ""));
      const state = form.querySelector(".machine-state");
      state.textContent = "…";
      try {
        const res = await fetch(R.machine.replace("/0/", "/" + c.id + "/"),
                                { method: "POST", body: new FormData(form) });
        if (!res.ok) throw new Error();
        // Le cran a changé : toutes les charges proposées aussi. Le plus sûr
        // est de recharger ; l'exercice ouvert et le chrono sont conservés.
        remember("weights", c.id, null);
        location.reload();
      } catch (err) {
        state.textContent = "non enregistré, réessaie";
      }
    });
  });

  /* ---------- démonstration : agrandir, animer l'exercice ouvert ---------- */
  document.querySelectorAll(".exo-demo").forEach((img) =>
    img.addEventListener("click", () => img.classList.toggle("big")));
  if (!REDUCED) {
    setInterval(() => {
      if (document.hidden) return;
      const img = document.querySelector(".exo-panel:not([hidden]) .exo-demo");
      if (!img || !img.dataset.alt) return;
      const tmp = img.src;
      img.src = img.dataset.alt;
      img.dataset.alt = tmp;
    }, 1300);
  }

  /* ---------- démarrage, et retour dans l'appli ---------- */
  function start() {
    const st = load();
    cards.forEach((c) => {
      const d = c.data, w = c.form.elements.weight;
      if (w) {
        const saved = st.weights && st.weights[c.id];
        w.value = saved != null && saved !== "" ? saved
          : (d.done.length ? d.done[d.done.length - 1].v : d.start);
      }
      render(c);
      prefillReps(c);
      const text = st.advice && st.advice[c.id];
      if (text && d.done.length) { c.advice.textContent = text; c.advice.hidden = false; }
    });
    refresh();

    // L'exercice ouvert : celui qu'on avait quitté ; sinon, en séance
    // normale, le premier commencé puis le premier à faire. En reprise et en
    // plyo, rien d'ouvert d'office : choisir EST le geste.
    let focus = st.focus && byId(st.focus) ? st.focus : null;
    if (!focus && cards.length) {
      const started = cards.find((c) => c.data.done.length > 0 && c.data.done.length < c.data.sets);
      const todo = cards.find((c) => c.data.done.length < c.data.sets);
      const first = started || (MODE === "force" ? todo : null);
      focus = first ? first.id : null;
    }
    select(focus, false);

    if (st.deadline && st.deadline > Date.now()) {
      deadline = st.deadline;
      timer.hidden = false;
      clearInterval(iv); iv = setInterval(tick, 250); tick();
    }
  }
  window.addEventListener("pageshow", (e) => { if (e.persisted && deadline > Date.now()) tick(); });

  const forget = () => { try { localStorage.removeItem(KEY); } catch (e) { /* rien */ } };
  document.querySelector("form.finish").addEventListener("submit", forget);
  const cancel = document.querySelector("form.cancel");
  if (cancel) cancel.addEventListener("submit", (e) => { if (!e.defaultPrevented) forget(); });

  start();
})();

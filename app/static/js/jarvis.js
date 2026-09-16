/* J.A.R.V.I.S — globe, chat, pavé numérique, voix.
   Aucune dépendance : tout tient ici et reste lisible dans six mois. */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var URLS = window.JARVIS.urls;
  var PAVE = window.JARVIS.pave;

  /* ====================================================================
     LE GLOBE

     600 points sur une sphère, reliés à leurs voisins proches.

     LE POINT QUI DÉCIDE DE LA FLUIDITÉ : les liaisons sont calculées UNE
     SEULE FOIS. La sphère est rigide — deux points voisins le restent
     quelle que soit la rotation. Les recalculer à chaque image, ce serait
     360 000 comparaisons soixante fois par seconde pour un résultat qui ne
     change jamais. Chaque image ne fait plus que tourner, projeter, tracer.
     ==================================================================== */
  var cv = $("globe"), ctx = cv.getContext("2d");
  var N = 600, RAYON_LIEN = 0.17, pts = [], liens = [], dpr = 1;

  // Spirale de Fibonacci : la seule façon simple de répartir N points
  // régulièrement sur une sphère. Un tirage aléatoire ferait des paquets
  // aux pôles, et une grille latitude/longitude aussi.
  (function semer() {
    var phi = Math.PI * (3 - Math.sqrt(5));
    for (var i = 0; i < N; i++) {
      var y = 1 - (i / (N - 1)) * 2;
      var r = Math.sqrt(Math.max(0, 1 - y * y));
      var t = phi * i;
      pts.push({ x: Math.cos(t) * r, y: y, z: Math.sin(t) * r });
    }
    for (var a = 0; a < N; a++) {
      for (var b = a + 1; b < N; b++) {
        var dx = pts[a].x - pts[b].x, dy = pts[a].y - pts[b].y,
            dz = pts[a].z - pts[b].z;
        if (dx * dx + dy * dy + dz * dz < RAYON_LIEN * RAYON_LIEN) {
          liens.push([a, b]);
        }
      }
    }
  })();

  function dimensionner() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    cv.width = window.innerWidth * dpr;
    cv.height = window.innerHeight * dpr;
  }
  window.addEventListener("resize", dimensionner);
  dimensionner();

  var angle = 0, intensite = 0;   // intensite monte quand Jarvis réfléchit

  function dessiner() {
    var w = cv.width, h = cv.height;
    var cx = w / 2, cy = h / 2;
    var R = Math.min(w, h) * 0.30;
    ctx.clearRect(0, 0, w, h);

    var cos = Math.cos(angle), sin = Math.sin(angle);
    var proj = new Array(N);
    for (var i = 0; i < N; i++) {
      var p = pts[i];
      var x = p.x * cos - p.z * sin;
      var z = p.x * sin + p.z * cos;
      // Perspective simple : plus un point est loin, plus il est petit et pâle.
      var k = 1 / (2.4 - z);
      proj[i] = { sx: cx + x * R * k * 2.4, sy: cy + p.y * R * k * 2.4,
                  a: Math.max(0, (z + 1) / 2) };
    }

    ctx.lineWidth = dpr * 0.6;
    for (var l = 0; l < liens.length; l++) {
      var A = proj[liens[l][0]], B = proj[liens[l][1]];
      var op = Math.min(A.a, B.a) * (0.16 + intensite * 0.22);
      if (op < 0.02) continue;
      ctx.strokeStyle = "rgba(70,215,245," + op.toFixed(3) + ")";
      ctx.beginPath();
      ctx.moveTo(A.sx, A.sy);
      ctx.lineTo(B.sx, B.sy);
      ctx.stroke();
    }
    for (var j = 0; j < N; j++) {
      var P = proj[j];
      ctx.fillStyle = "rgba(140,238,255," + (P.a * (0.5 + intensite * 0.5)).toFixed(3) + ")";
      ctx.fillRect(P.sx, P.sy, dpr * 1.6, dpr * 1.6);
    }

    angle += 0.0016 + intensite * 0.004;
    intensite += (cible - intensite) * 0.05;
    requestAnimationFrame(dessiner);
  }
  var cible = 0;
  requestAnimationFrame(dessiner);

  /* ====================================================================
     BARRE HAUTE
     ==================================================================== */
  function deuxChiffres(n) { return n < 10 ? "0" + n : "" + n; }

  // L'horloge bat localement : demander l'heure au serveur chaque seconde
  // serait une requête par seconde pour une information que le navigateur a.
  setInterval(function () {
    var d = new Date();
    $("horloge").textContent = deuxChiffres(d.getHours()) + ":" +
      deuxChiffres(d.getMinutes()) + ":" + deuxChiffres(d.getSeconds());
  }, 1000);

  function rafraichirEtat() {
    fetch(URLS.etat).then(function (r) { return r.json(); }).then(function (e) {
      $("date").textContent = e.date;
      // host.py renvoie None au-delà de cinq minutes : on affiche alors --%
      // plutôt que le dernier chiffre connu. Un indicateur qui ment est pire
      // qu'un indicateur vide.
      var h = e.hote || {};
      $("ram").textContent = h.mem_pct ? h.mem_pct + "%" : "--%";
      $("cpu").textContent = (h.cpu_pct || h.cpu_pct === 0) ? h.cpu_pct + "%" : "--%";
      $("conteneurs").textContent = h.total ? (h.up + "/" + h.total + " OK") : "HORS LIGNE";

      var lien = $("lien"), o = e.ollama || {};
      lien.textContent = o.etat === "pret" ? "● connecté"
        : o.etat === "modele-absent" ? "● modèle absent" : "● hors ligne";
      lien.classList.toggle("hs", o.etat !== "pret");

      var t = e.taches || {};
      $("pastille-taches").textContent = t.pending ? t.pending : "";
    }).catch(function () {
      $("lien").textContent = "● serveur muet";
      $("lien").classList.add("hs");
    });
  }
  rafraichirEtat();
  setInterval(rafraichirEtat, 5000);

  /* ====================================================================
     LE JOURNAL
     ==================================================================== */
  var journal = $("journal"), historique = [], derniereReponse = "";

  function ecrire(qui, texte, options) {
    options = options || {};
    var bloc = document.createElement("div");
    bloc.className = "tour" + (qui === "moi" ? " moi" : "");
    var titre = document.createElement("div");
    titre.className = "qui";
    titre.textContent = qui === "moi" ? "vous" : "jarvis";
    bloc.appendChild(titre);
    var p = document.createElement("p");
    p.className = "dit";
    p.textContent = texte;
    bloc.appendChild(p);
    if (options.outils && options.outils.length) {
      var o = document.createElement("div");
      o.className = "outils";
      o.textContent = "↳ " + options.outils.join(" · ");
      bloc.appendChild(o);
    }
    if (options.brut) {
      var pre = document.createElement("pre");
      pre.className = "brut";
      pre.textContent = options.brut;
      bloc.appendChild(pre);
    }
    journal.appendChild(bloc);
    journal.scrollTop = journal.scrollHeight;
  }

  /* ====================================================================
     LA VOIX

     On tente Piper sur le serveur ; s'il n'est pas installé la route répond
     503 et on bascule sur la synthèse du navigateur. C'est ce qui donne une
     voix à Jarvis dès aujourd'hui, avant même le pilote NVIDIA.
     ==================================================================== */
  var voixActive = true, audio = null;

  function taire() {
    if (audio) { audio.pause(); audio = null; }
    if (window.speechSynthesis) window.speechSynthesis.cancel();
  }

  function parler(texte) {
    if (!voixActive || !texte) return;
    taire();
    fetch(URLS.voix + "?texte=" + encodeURIComponent(texte))
      .then(function (r) {
        if (!r.ok) throw new Error("piper absent");
        return r.blob();
      })
      .then(function (b) {
        audio = new Audio(URL.createObjectURL(b));
        audio.play();
      })
      .catch(function () {
        if (!window.speechSynthesis) return;
        var u = new SpeechSynthesisUtterance(texte);
        u.lang = "fr-FR";
        u.rate = 1.05;
        window.speechSynthesis.speak(u);
      });
  }

  $("btn-stop").addEventListener("click", taire);
  $("btn-voix").addEventListener("click", function () {
    voixActive = !voixActive;
    $("etat-voix").textContent = voixActive ? "ON" : "OFF";
    if (!voixActive) taire();
  });

  /* ====================================================================
     DEMANDER
     ==================================================================== */
  var enCours = false;

  function demander(question) {
    if (enCours || !question) return;
    enCours = true;
    cible = 1;
    ecrire("moi", question);
    $("etat").textContent = "réflexion";
    $("etat").classList.add("actif");

    fetch(URLS.demander, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: question, historique: historique })
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var brut = null;
        if (d.repli && d.repli.donnees) {
          brut = JSON.stringify(d.repli.donnees, null, 2);
        }
        ecrire("jarvis", d.reponse, { outils: d.outils, brut: brut });
        derniereReponse = d.reponse;
        if (d.ok) {
          historique.push({ role: "user", content: question });
          historique.push({ role: "assistant", content: d.reponse });
          parler(d.reponse);
        }
      })
      .catch(function (e) {
        ecrire("jarvis", "Liaison interrompue : " + e.message);
      })
      .finally(function () {
        enCours = false;
        cible = 0;
        $("etat").textContent = "en attente";
        $("etat").classList.remove("actif");
      });
  }

  $("chat").addEventListener("submit", function (ev) {
    ev.preventDefault();
    var q = $("question").value.trim();
    $("question").value = "";
    demander(q);
  });

  /* ====================================================================
     LE PAVÉ NUMÉRIQUE

     `event.code` distingue Numpad7 de Digit7, donc la touche du pavé ne se
     confond pas avec celle du haut du clavier. Ce que le navigateur ne sait
     PAS, c'est de quel clavier physique vient la frappe : d'où la règle
     ci-dessous — un raccourci ne part que si le champ de saisie n'a pas le
     focus. Le chat reste un chat, le pavé reste un pavé.
     ==================================================================== */
  var phrases = {};
  PAVE.forEach(function (ligne) { phrases[ligne[0]] = ligne[2]; });

  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") { $("question").blur(); return; }
    if (document.activeElement === $("question")) return;   // on tape, on n'agit pas

    if (ev.code === "NumpadSubtract") { ev.preventDefault(); taire(); return; }
    if (ev.code === "NumpadAdd") {
      ev.preventDefault();
      parler(derniereReponse);
      return;
    }
    var phrase = phrases[ev.code];
    if (phrase) { ev.preventDefault(); demander(phrase); return; }

    // Toute autre frappe imprimable relance la saisie : on n'a pas à viser
    // le champ à la souris pour poser une vraie question.
    if (ev.key.length === 1 && !ev.ctrlKey && !ev.altKey && !ev.metaKey) {
      $("question").focus();
    }
  });

  /* ====================================================================
     PANNEAUX
     ==================================================================== */
  $("bascule-menu").addEventListener("click", function () {
    $("menu").hidden = !$("menu").hidden;
  });
  $("btn-pave").addEventListener("click", function () {
    $("aide-pave").hidden = !$("aide-pave").hidden;
  });
  $("aide-pave").addEventListener("click", function () {
    $("aide-pave").hidden = true;
  });

  ecrire("jarvis", "Bonsoir monsieur. Systèmes en ligne, à votre disposition.");
})();

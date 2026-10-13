/* Jarvis : globe, conversation, pavé numérique, tâches, voix.
   Aucune dépendance : tout tient ici et reste lisible dans six mois. */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var URLS = window.JARVIS.urls;
  var PAVE = window.JARVIS.pave;
  var calme = window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ====================================================================
     LE GLOBE

     600 points sur une sphère, reliés à leurs voisins proches.

     LE POINT QUI DÉCIDE DE LA FLUIDITÉ : les liaisons sont calculées UNE
     SEULE FOIS. La sphère est rigide, deux points voisins le restent
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

  // Le globe se loge dans la place que lui laisse la conversation : son
  // centre et son rayon suivent le bloc « presence », qui rétrécit quand le
  // journal s'allonge et se déplace quand la page défile sur téléphone.
  var presence = $("presence"), centre = { x: 0, y: 0, r: 0 };

  function ancrer() {
    var b = presence.getBoundingClientRect();
    centre.x = (b.left + b.width / 2) * dpr;
    centre.y = (b.top + b.height / 2) * dpr;
    // 0,42 et non 0,5 : la perspective grossit les points proches d'un
    // dixième, et il faut qu'ils restent dans le bloc.
    centre.r = Math.max(48, Math.min(b.width, b.height) * 0.42) * dpr;
  }

  function dimensionner() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    cv.width = window.innerWidth * dpr;
    cv.height = window.innerHeight * dpr;
    ancrer();
  }
  window.addEventListener("resize", dimensionner);
  window.addEventListener("scroll", ancrer, { passive: true });
  if (window.ResizeObserver) new ResizeObserver(ancrer).observe(presence);
  dimensionner();

  var angle = 0, intensite = 0, cible = 0;   // cible monte quand Jarvis réfléchit

  function dessiner() {
    var cx = centre.x, cy = centre.y, R = centre.r;
    ctx.clearRect(0, 0, cv.width, cv.height);

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

    // Qui a demandé moins de mouvement garde un globe immobile : il
    // s'éclaire encore quand Jarvis réfléchit, mais il ne tourne plus.
    if (!calme) angle += 0.0016 + intensite * 0.004;
    intensite += (cible - intensite) * 0.05;
    requestAnimationFrame(dessiner);
  }
  requestAnimationFrame(dessiner);

  /* ====================================================================
     LE BANDEAU ET LE RAIL
     ==================================================================== */
  function deuxChiffres(n) { return n < 10 ? "0" + n : "" + n; }

  // L'horloge bat localement : demander l'heure au serveur chaque seconde
  // serait une requête par seconde pour une information que le navigateur a.
  function battre() {
    var d = new Date();
    $("horloge").textContent = deuxChiffres(d.getHours()) + ":" +
      deuxChiffres(d.getMinutes()) + ":" + deuxChiffres(d.getSeconds());
    $("date").textContent = d.toLocaleDateString("fr-FR",
      { weekday: "long", day: "numeric", month: "long" });
  }
  battre();
  setInterval(battre, 1000);

  // host.py renvoie None quand le relevé a plus de cinq minutes : on
  // affiche alors « -- » plutôt que le dernier chiffre connu. Un indicateur
  // qui ment est pire qu'un indicateur vide.
  function mesurer(id, valeur) {
    var connu = valeur || valeur === 0;
    var bloc = $("m-" + id);
    $(id).textContent = connu ? valeur + " %" : "--";
    bloc.querySelector(".niveau").style.setProperty("--n", (connu ? valeur : 0) + "%");
    bloc.classList.toggle("alerte", connu && valeur >= 90);
  }

  var tachesVues = "";

  function afficherTaches(t) {
    var liste = t.liste || [];
    // Le relevé arrive toutes les cinq secondes : on ne redessine que si la
    // liste a changé, sinon un clic en cours tomberait sur un bouton neuf.
    var empreinte = JSON.stringify(t);
    if (empreinte === tachesVues) return;
    tachesVues = empreinte;

    var ul = $("liste-taches");
    ul.textContent = "";
    liste.forEach(function (x) {
      var li = document.createElement("li");
      if (x.retard) li.className = "retard";
      var coche = document.createElement("button");
      coche.type = "button";
      coche.className = "coche";
      coche.setAttribute("aria-label", "Terminer : " + x.texte);
      coche.addEventListener("click", function () { terminer(x.id, li); });
      var texte = document.createElement("span");
      texte.className = "texte";
      texte.textContent = x.texte;
      li.appendChild(coche);
      li.appendChild(texte);
      if (x.echeance) {
        var quand = document.createElement("span");
        quand.className = "echeance";
        quand.textContent = x.echeance;
        li.appendChild(quand);
      }
      ul.appendChild(li);
    });

    var compte = $("compte-taches");
    compte.textContent = !t.pending ? ""
      : t.late ? t.pending + ", dont " + t.late + " en retard" : "" + t.pending;
    compte.classList.toggle("retard", !!t.late);
    $("taches-vides").hidden = liste.length > 0;
    $("lien-taches").textContent = t.pending > liste.length
      ? "Voir les " + t.pending + " tâches" : "Toutes les tâches";
  }

  function terminer(id, li) {
    li.classList.add("fait");
    fetch(URLS.terminer.replace("/0/", "/" + id + "/"), { method: "POST" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) throw new Error("refus");
        // Un court instant barrée, pour qu'on voie ce qu'on vient de cocher.
        setTimeout(function () { afficherTaches(d.taches); }, 700);
      })
      .catch(function () {
        li.classList.remove("fait");
        annoncer("La tâche n'a pas pu être cochée.");
      });
  }

  function rafraichirEtat() {
    fetch(URLS.etat).then(function (r) { return r.json(); }).then(function (e) {
      var h = e.hote || {}, o = e.ollama || {};
      mesurer("cpu", h.cpu_pct);
      mesurer("ram", h.total ? h.mem_pct : null);
      mesurer("disque", h.total ? h.disk_pct : null);

      var lien = $("lien");
      lien.textContent = o.etat === "pret" ? "Modèle prêt"
        : o.etat === "modele-absent" ? "Modèle absent" : "Modèle hors ligne";
      lien.classList.toggle("hs", o.etat !== "pret");

      var conteneurs = $("conteneurs");
      var panne = h.down && h.down.length;
      conteneurs.textContent = !h.total ? "Relevé du serveur indisponible"
        : panne ? "À l'arrêt : " + h.down.join(", ")
        : h.up + " conteneurs sur " + h.total + " en marche";
      conteneurs.classList.toggle("alerte", !h.total || !!panne);
      $("allume").textContent = h.total && h.uptime ? "Allumé depuis " + h.uptime : "";
      $("modele").textContent = o.modele ? "Modèle " + o.modele : "";

      afficherTaches(e.taches || {});
    }).catch(function () {
      $("lien").textContent = "Serveur muet";
      $("lien").classList.add("hs");
    });
  }
  rafraichirEtat();
  setInterval(rafraichirEtat, 5000);

  /* ====================================================================
     LE JOURNAL
     ==================================================================== */
  var journal = $("journal"), historique = [], derniereReponse = "";

  // Les outils portent des noms de fonction ; à l'écran, on lit des mots.
  var OUTILS = {
    seance_du_jour: "séance du jour", assiduite: "assiduité",
    conseil_du_coach: "conseil du coach", progression: "progression",
    prochains_evenements: "agenda", veille_emploi: "veille emploi",
    etat_serveur: "état du serveur", taches_en_cours: "tâches en cours",
    ajouter_tache: "tâche ajoutée", terminer_tache: "tâche terminée"
  };

  function ecrire(qui, texte, options) {
    options = options || {};
    var bloc = document.createElement("div");
    bloc.className = "tour" + (qui === "moi" ? " moi" : "");
    var p = document.createElement("p");
    p.className = "dit";
    p.textContent = texte;
    bloc.appendChild(p);
    if (options.outils && options.outils.length) {
      var source = document.createElement("div");
      source.className = "source";
      source.textContent = "Source : " + options.outils.map(function (o) {
        return OUTILS[o] || o.replace(/_/g, " ");
      }).join(", ");
      bloc.appendChild(source);
    }
    if (options.brut) {
      var details = document.createElement("details");
      details.className = "brut";
      var resume = document.createElement("summary");
      resume.textContent = "Données brutes";
      var pre = document.createElement("pre");
      pre.textContent = options.brut;
      details.appendChild(resume);
      details.appendChild(pre);
      bloc.appendChild(details);
    }
    journal.appendChild(bloc);
    journal.scrollTop = journal.scrollHeight;
    ancrer();
  }

  // La ligne d'état sous le champ : « Prêt », « Jarvis réfléchit », ou un
  // message court qui s'efface tout seul.
  var retour = null;

  function annoncer(texte) {
    clearTimeout(retour);
    $("etat").textContent = texte;
    retour = setTimeout(function () {
      if (!enCours) $("etat").textContent = "Prêt";
    }, 4000);
  }

  /* ====================================================================
     LA VOIX

     On tente Piper sur le serveur ; s'il n'est pas installé la route répond
     503 et on bascule sur la synthèse du navigateur. C'est ce qui donne une
     voix à Jarvis sans rien installer.
     ==================================================================== */
  var voixActive = true, audio = null;

  // Le choix survit au rechargement : sur un téléphone, une page qui se
  // remet à parler toute seule est une mauvaise surprise.
  try { voixActive = localStorage.getItem("jarvis-voix") !== "non"; } catch (e) {}

  function montrerVoix() {
    $("btn-voix").textContent = voixActive ? "Voix activée" : "Voix coupée";
    $("btn-voix").setAttribute("aria-pressed", voixActive ? "true" : "false");
  }
  montrerVoix();

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
    try { localStorage.setItem("jarvis-voix", voixActive ? "oui" : "non"); } catch (e) {}
    montrerVoix();
    if (!voixActive) taire();
  });

  /* ====================================================================
     DEMANDER
     ==================================================================== */
  var enCours = false;

  function demander(question, touche) {
    if (enCours || !question) return;
    enCours = true;
    cible = 1;
    clearTimeout(retour);
    ecrire("moi", question);
    $("etat").textContent = "Jarvis réfléchit";
    $("etat").classList.add("actif");
    if (touche) touche.classList.add("en-cours");

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
        // Jarvis a pu ajouter ou cocher une tâche : on n'attend pas le
        // prochain relevé pour le montrer.
        rafraichirEtat();
      })
      .catch(function () {
        ecrire("jarvis", "La liaison avec le serveur s'est interrompue. " +
          "Vérifiez qu'Awen répond, puis reposez la question.");
      })
      .finally(function () {
        enCours = false;
        cible = 0;
        $("etat").textContent = "Prêt";
        $("etat").classList.remove("actif");
        if (touche) touche.classList.remove("en-cours");
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
     ci-dessous, un raccourci ne part que si le champ de saisie n'a pas le
     focus. Le chat reste un chat, le pavé reste un pavé.

     Les touches dessinées à l'écran font la même chose que les vraies : au
     doigt ou à la souris, on clique celle qu'on aurait enfoncée.
     ==================================================================== */
  var phrases = {}, touches = {};
  PAVE.forEach(function (ligne) { phrases[ligne[0]] = ligne[2]; });

  function actionner(code) {
    var touche = touches[code];
    if (!touche || touche.disabled) return;
    touche.classList.add("appui");
    setTimeout(function () { touche.classList.remove("appui"); }, 180);

    if (code === "NumpadSubtract") { taire(); return; }
    if (code === "NumpadAdd") {
      if (!derniereReponse) annoncer("Rien à répéter pour l'instant.");
      else if (!voixActive) annoncer("La voix est coupée : réactivez-la pour entendre la réponse.");
      else parler(derniereReponse);
      return;
    }
    if (code === "NumpadDivide") { $("question").focus(); return; }
    if (enCours) { annoncer("Une question est déjà en route."); return; }
    demander(phrases[code], touche);
  }

  Array.prototype.forEach.call(document.querySelectorAll(".touche"), function (t) {
    touches[t.getAttribute("data-code")] = t;
    t.addEventListener("click", function () {
      // On rend le focus à la page : sinon la touche Entrée du pavé
      // recliquerait ce bouton au lieu de lancer « Développe ».
      t.blur();
      actionner(t.getAttribute("data-code"));
    });
  });

  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") { $("question").blur(); return; }
    if (document.activeElement === $("question")) return;   // on tape, on n'agit pas

    if (touches[ev.code] && !touches[ev.code].disabled) {
      ev.preventDefault();
      actionner(ev.code);
      return;
    }
    // Toute autre frappe imprimable relance la saisie : on n'a pas à viser
    // le champ à la souris pour poser une vraie question.
    if (ev.key.length === 1 && !ev.ctrlKey && !ev.altKey && !ev.metaKey) {
      $("question").focus();
    }
  });

  var heure = new Date().getHours();
  ecrire("jarvis", (heure >= 18 || heure < 5 ? "Bonsoir" : "Bonjour") +
    " monsieur. Je suis à votre disposition.");
})();

/* La dictée : le micro du navigateur, puis Awen range la phrase.
 *
 * La reconnaissance vocale est celle de Chrome (webkitSpeechRecognition),
 * en français. Elle ne marche que sur une adresse HTTPS, d'où l'adresse
 * Tailscale. Sans elle (autre navigateur), le champ texte reste : le micro
 * du clavier du téléphone y dicte aussi.
 */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const micro = $("micro"), etat = $("etat"), entendu = $("entendu");
  const apercu = $("apercu"), fait = $("fait");
  const titre = $("titre"), quand = $("quand"), jour = $("jour");
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  let dernier = null;          // {type, id} de ce qui vient d'être ajouté
  let rec = null;

  function dire(texte, classe) {
    etat.textContent = texte;
    etat.className = "dk-etat" + (classe ? " " + classe : "");
  }

  async function appel(url, corps) {
    const r = await fetch(url, corps === undefined ? {} : {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(corps),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.erreur || "Awen n'a pas répondu.");
    return data;
  }

  // --- écouter ------------------------------------------------------------

  function ecouter() {
    if (!SR) {
      dire("Ce navigateur n'a pas de reconnaissance vocale : ouvre la page dans Chrome, "
           + "ou dicte avec le micro du clavier dans le champ en bas.");
      $("phrase").focus();
      return;
    }
    if (rec) { rec.stop(); return; }           // deuxième touche : on arrête
    apercu.hidden = true;
    fait.hidden = true;
    entendu.textContent = "";
    let final = "";
    rec = new SR();
    rec.lang = "fr-FR";
    rec.interimResults = true;
    rec.maxAlternatives = 1;
    rec.onstart = () => { micro.classList.add("ecoute"); dire("J'écoute…"); };
    rec.onresult = (e) => {
      let provisoire = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) final += r[0].transcript; else provisoire += r[0].transcript;
      }
      entendu.textContent = (final + " " + provisoire).trim();
    };
    rec.onerror = (e) => {
      if (e.error === "not-allowed" || e.error === "service-not-allowed") {
        dire("Le micro est refusé : autorise-le pour cette page dans Chrome "
             + "(cadenas à gauche de l'adresse, Autorisations).", "erreur");
      } else if (e.error === "no-speech") {
        dire("Je n'ai rien entendu. Touche le micro pour réessayer.");
      } else if (e.error !== "aborted") {
        dire("Le micro s'est coupé (" + e.error + "). Touche-le pour réessayer.", "erreur");
      }
    };
    rec.onend = () => {
      rec = null;
      micro.classList.remove("ecoute");
      const phrase = entendu.textContent.trim();
      if (phrase) analyser(phrase);
      else if (etat.textContent === "J'écoute…") dire("Touche le micro et dis la chose à faire.");
    };
    try { rec.start(); } catch (e) { rec = null; }
  }

  // --- comprendre ---------------------------------------------------------

  async function analyser(phrase) {
    dire("Je range…");
    try {
      const r = await appel("/dictee/analyser", {texte: phrase});
      titre.value = r.titre;
      quand.value = r.quand;
      jour.value = r.jour;
      $("l-jour").hidden = !r.jour;
      montrerLibelle(r.libelle);
      apercu.hidden = false;
      dire("Vérifie, puis ajoute.");
    } catch (e) {
      dire(e.message, "erreur");
    }
  }

  function montrerLibelle(texte) {
    const date = quand.value || jour.value;
    $("libelle").textContent = date ? texte + " · agenda Awen" : "Sans date : ira dans tes tâches d'Awen.";
    $("ajouter").textContent = date ? "Ajouter à l'agenda" : "Ajouter aux tâches";
  }

  async function corriger() {
    if (quand.value) jour.value = "";
    $("l-jour").hidden = !jour.value;
    const q = new URLSearchParams({quand: quand.value, jour: jour.value});
    try { montrerLibelle((await appel("/dictee/libelle?" + q)).libelle); } catch (e) { /* le libellé attendra */ }
  }

  // --- ranger -------------------------------------------------------------

  async function ajouter() {
    const bouton = $("ajouter");
    bouton.disabled = true;
    try {
      const r = await appel("/dictee/ajouter", {titre: titre.value, quand: quand.value, jour: jour.value});
      dernier = {type: r.type, id: r.id};
      $("message").textContent = "✓ " + titre.value.trim() + ". " + r.message;
      apercu.hidden = true;
      fait.hidden = false;
      $("annuler").disabled = false;
      dire("C'est noté.", "ok");
      if (navigator.vibrate) navigator.vibrate(30);
    } catch (e) {
      dire(e.message, "erreur");
    } finally {
      bouton.disabled = false;
    }
  }

  async function annuler() {
    if (!dernier) return;
    $("annuler").disabled = true;
    try {
      await appel("/dictee/annuler", dernier);
      dernier = null;
      $("message").textContent = "Annulé : rien n'a été gardé.";
      dire("Touche le micro et dis la chose à faire.");
    } catch (e) {
      $("annuler").disabled = false;
      dire(e.message, "erreur");
    }
  }

  function recommencer() {
    apercu.hidden = true;
    fait.hidden = true;
    entendu.textContent = "";
    ecouter();
  }

  micro.addEventListener("click", ecouter);
  $("refaire").addEventListener("click", recommencer);
  $("encore").addEventListener("click", recommencer);
  $("ajouter").addEventListener("click", ajouter);
  $("annuler").addEventListener("click", annuler);
  quand.addEventListener("change", corriger);
  jour.addEventListener("change", corriger);
  $("ecrire").addEventListener("submit", (e) => {
    e.preventDefault();
    const phrase = $("phrase").value.trim();
    if (!phrase) return;
    entendu.textContent = phrase;
    $("phrase").value = "";
    analyser(phrase);
  });

  // Ouverte depuis l'icône de l'écran d'accueil (?auto=1) : le micro écoute
  // tout de suite. Si Chrome exige d'abord une touche, le bouton est là.
  if (new URLSearchParams(location.search).has("auto")) ecouter();
})();

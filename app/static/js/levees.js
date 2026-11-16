/* Levées de fonds : suivi de la collecte, copie des adresses, éditeur du mail.
 *
 * La collecte et la rédaction tournent sur le serveur, en arrière-plan : la
 * page demande l'état toutes les trois secondes et se recharge quand c'est
 * fini. L'éditeur enregistre seul, une seconde après la dernière frappe,
 * comme celui des lettres.
 */
(function () {
  "use strict";

  const copier = async (texte, bouton) => {
    try {
      await navigator.clipboard.writeText(texte);
      const avant = bouton.textContent;
      bouton.textContent = "copié";
      bouton.classList.add("ok");
      setTimeout(() => { bouton.textContent = avant; bouton.classList.remove("ok"); }, 1200);
    } catch (e) {
      window.prompt("Copie à la main :", texte);
    }
  };
  document.querySelectorAll(".lv-copy[data-copie]").forEach((b) => {
    b.addEventListener("click", () => copier(b.dataset.copie, b));
  });

  // --- la collecte ----------------------------------------------------------
  const collecte = document.getElementById("lv-collecte");
  if (collecte && collecte.dataset.enCours) {
    const message = document.getElementById("lv-message");
    const suivre = async () => {
      try {
        const r = await fetch(collecte.dataset.etat, { cache: "no-store" });
        const etat = await r.json();
        if (etat.etat !== "en_cours") { location.reload(); return; }
        if (message) message.textContent = etat.message;
      } catch (e) { /* le réseau hoquette : on retente */ }
      setTimeout(suivre, 3000);
    };
    setTimeout(suivre, 3000);
  }

  // Le destinataire libre remplace le menu quand il est rempli.
  document.querySelectorAll(".lv-mail-form").forEach((f) => {
    f.addEventListener("submit", () => {
      const libre = f.elements.destinataire_libre;
      const menu = f.elements.destinataire;
      if (libre && libre.value.trim() && menu && menu.tagName === "SELECT") menu.value = "";
    });
  });

  // --- l'éditeur --------------------------------------------------------------
  const editeur = document.getElementById("lv-editor");
  if (!editeur) return;
  const attente = editeur.querySelector(".lt-wait");
  if (attente && !attente.hidden) {
    const suivre = async () => {
      try {
        const r = await fetch(editeur.dataset.etat, { cache: "no-store" });
        const etat = await r.json();
        if (etat.etat !== "generation") { location.reload(); return; }
      } catch (e) { /* on retente */ }
      setTimeout(suivre, 3000);
    };
    setTimeout(suivre, 3000);
  }

  const form = document.getElementById("lv-form");
  if (!form) return;
  const enregistre = document.getElementById("lt-saved");
  const compteur = document.getElementById("lv-mots");
  const mots = () => (form.elements.corps.value.match(/[\p{L}\p{N}'-]+/gu) || []).length;

  let minuterie = null;
  const enregistrer = async (keepalive = false) => {
    clearTimeout(minuterie);
    minuterie = null;
    const d = {};
    for (const el of form.elements) if (el.name) d[el.name] = el.value;
    try {
      const r = await fetch(editeur.dataset.enregistrer, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(d), keepalive,
      });
      if (!r.ok) throw new Error(r.status);
      enregistre.textContent = "Enregistré à " +
        new Date().toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
    } catch (e) {
      enregistre.textContent = "Pas enregistré : le serveur ne répond pas.";
    }
  };
  form.addEventListener("input", () => {
    compteur.textContent = mots();
    enregistre.textContent = "Modifié";
    clearTimeout(minuterie);
    minuterie = setTimeout(enregistrer, 1000);
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden" && minuterie) enregistrer(true);
  });
  form.elements.objet.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") { ev.preventDefault(); form.elements.corps.focus(); }
  });

  document.querySelectorAll(".lv-copy[data-copie-de]").forEach((b) => {
    b.addEventListener("click", () => copier(form.elements[b.dataset.copieDe].value, b));
  });
  document.getElementById("lv-copier-mail").addEventListener("click", (ev) => {
    const corps = form.elements.corps.value.trim();
    const signature = form.elements.signature.value.trim();
    copier(signature ? corps + "\n\n" + signature : corps, ev.currentTarget);
  });
})();

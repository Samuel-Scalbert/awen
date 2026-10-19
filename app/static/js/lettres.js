/* Éditeur de lettre : suivi de la génération, enregistrement, PDF.
 *
 * Pendant que Claude écrit, la page demande l'état toutes les deux
 * secondes, puis se recharge : le serveur rend alors la lettre complète,
 * sans rien à reconstruire ici.
 *
 * Chaque modification s'enregistre seule, une seconde après la dernière
 * frappe : une correction perdue parce qu'on a oublié un bouton, c'est
 * justement ce dont Claude aurait dû apprendre.
 */
(function () {
  "use strict";

  const editeur = document.getElementById("lt-editor");
  if (!editeur) return;
  const urls = editeur.dataset;
  const form = document.getElementById("lt-form");
  const enregistre = document.getElementById("lt-saved");
  const compteur = document.getElementById("lt-mots");
  const boutonPdf = document.getElementById("lt-pdf");
  const erreurPdf = document.getElementById("lt-pdf-error");

  // --- la génération ------------------------------------------------------
  const attente = editeur.querySelector(".lt-wait");
  if (attente && !attente.hidden) {
    const suivre = async () => {
      try {
        const r = await fetch(urls.etat, { cache: "no-store" });
        const etat = await r.json();
        if (etat.etat !== "generation") {
          location.reload();
          return;
        }
      } catch (e) {
        // Le réseau hoquette : on retente au tour suivant.
      }
      setTimeout(suivre, 2000);
    };
    setTimeout(suivre, 2000);
  }

  if (!form) return;

  // --- le compte de mots --------------------------------------------------
  const mots = () => {
    const texte = ["objet", "salutation", "corps"]
      .map((n) => form.elements[n].value).join(" ");
    return (texte.match(/[\p{L}\p{N}]+/gu) || []).length;
  };
  const majCompte = () => {
    const n = mots();
    compteur.textContent = n;
    compteur.parentElement.classList.toggle("over", n > 340);
  };

  // --- l'enregistrement ---------------------------------------------------
  const donnees = () => {
    const d = {};
    for (const el of form.elements) if (el.name) d[el.name] = el.value;
    return d;
  };
  let minuterie = null;
  const enregistrer = async () => {
    minuterie = null;
    enregistre.textContent = "Enregistrement…";
    try {
      const r = await fetch(urls.enregistrer, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(donnees()),
      });
      if (!r.ok) throw new Error(r.status);
      const h = new Date();
      enregistre.textContent = "Enregistré à " +
        h.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
    } catch (e) {
      enregistre.textContent = "Pas enregistré : le serveur ne répond pas.";
    }
  };
  form.addEventListener("input", () => {
    majCompte();
    enregistre.textContent = "Modifié";
    clearTimeout(minuterie);
    minuterie = setTimeout(enregistrer, 1000);
  });
  window.addEventListener("beforeunload", (ev) => {
    if (minuterie) {
      enregistrer();
      ev.preventDefault();
    }
  });

  // --- le PDF -------------------------------------------------------------
  boutonPdf.addEventListener("click", async () => {
    erreurPdf.hidden = true;
    boutonPdf.disabled = true;
    const libelle = boutonPdf.textContent;
    boutonPdf.textContent = "Mise en page…";
    clearTimeout(minuterie);
    minuterie = null;
    try {
      const corps = new FormData(form);
      const r = await fetch(urls.pdf, { method: "POST", body: corps });
      const type = r.headers.get("Content-Type") || "";
      if (!r.ok || !type.includes("pdf")) {
        let message = "Le PDF n'a pas pu être créé.";
        try { message = (await r.json()).erreur || message; } catch (e) { /* rien */ }
        throw new Error(message);
      }
      const fichier = await r.blob();
      // Un nom accentué arrive dans filename*, un nom ASCII dans filename.
      const entete = r.headers.get("Content-Disposition") || "";
      const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(entete);
      const simple = /filename="?([^";]+)"?/i.exec(entete);
      const lien = document.createElement("a");
      lien.href = URL.createObjectURL(fichier);
      lien.download = utf8 ? decodeURIComponent(utf8[1])
        : (simple ? simple[1] : "Lettre de motivation.pdf");
      document.body.appendChild(lien);
      lien.click();
      setTimeout(() => { URL.revokeObjectURL(lien.href); lien.remove(); }, 1000);
      enregistre.textContent = "PDF téléchargé, version enregistrée.";
    } catch (e) {
      erreurPdf.textContent = e.message;
      erreurPdf.hidden = false;
    } finally {
      boutonPdf.disabled = false;
      boutonPdf.textContent = libelle;
    }
  });

  majCompte();
})();

// main.js — Punto de entrada: conecta la interfaz con Firebase.
import { firebaseConfig } from "./config.js";
import { iniciarApp } from "./app.js";

if (firebaseConfig.apiKey === "PEGA_AQUI") {
  document.getElementById("btn-login").disabled = true;
  document.getElementById("login-msg").textContent =
    "Falta configurar Firebase: pega el firebaseConfig de tu proyecto en js/config.js (ver README).";
} else {
  const { crearBackendFirebase } = await import("./firebase-backend.js");
  iniciarApp(crearBackendFirebase(firebaseConfig));
}

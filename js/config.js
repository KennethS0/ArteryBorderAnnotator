// config.js — Lo único que hay que editar para conectar la app con tu proyecto de Firebase.
//
// 1) Consola de Firebase → ⚙ Configuración del proyecto → "Tus apps" → app web (</>)
//    → copia el objeto firebaseConfig aquí abajo.
//    Estos valores NO son secretos: identifican al proyecto. Lo que protege los datos son las
//    reglas de seguridad (firestore.rules y storage.rules) y la lista de anotadores autorizados.
export const firebaseConfig = {
  apiKey: "AIzaSyD56sfy5iQooZOAjHyQ0e-o6R3yoAv4Zsk",
  authDomain: "arteryborderannotator.firebaseapp.com",
  projectId: "arteryborderannotator",
  storageBucket: "arteryborderannotator.firebasestorage.app",
  messagingSenderId: "6246735352",
  appId: "1:6246735352:web:cb32ba09c6674120d7ca0d",
};

// Cuántos frames se espera que anote cada persona por video (solo para mostrar el progreso).
export const META_FRAMES_POR_VIDEO = 25;

// Segundos sin cambios antes de guardar automáticamente en Firestore.
export const AUTOGUARDADO_S = 1.5;

// config.js — Lo único que hay que editar para conectar la app con tu proyecto de Firebase.
//
// 1) Consola de Firebase → ⚙ Configuración del proyecto → "Tus apps" → app web (</>)
//    → copia el objeto firebaseConfig aquí abajo.
//    Estos valores NO son secretos: identifican al proyecto. Lo que protege los datos son las
//    reglas de seguridad (firestore.rules y storage.rules) y la lista de anotadores autorizados.
export const firebaseConfig = {
  apiKey: "PEGA_AQUI",
  authDomain: "TU-PROYECTO.firebaseapp.com",
  projectId: "TU-PROYECTO",
  storageBucket: "TU-PROYECTO.firebasestorage.app",
  messagingSenderId: "000000000000",
  appId: "1:000000000000:web:0000000000000000",
};

// Cuántos frames se espera que anote cada persona por video (solo para mostrar el progreso).
export const META_FRAMES_POR_VIDEO = 25;

// Segundos sin cambios antes de guardar automáticamente en Firestore.
export const AUTOGUARDADO_S = 1.5;

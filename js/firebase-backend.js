// firebase-backend.js — Todo lo que habla con Firebase está aquí.
// app.js solo usa esta interfaz, así que se puede probar con un backend falso.

import { initializeApp } from "https://www.gstatic.com/firebasejs/12.19.0/firebase-app.js";
import {
  getAuth, GoogleAuthProvider, signInWithPopup, signOut, onAuthStateChanged,
} from "https://www.gstatic.com/firebasejs/12.19.0/firebase-auth.js";
import {
  getFirestore, doc, getDoc, setDoc, deleteDoc, collection, query, where, getDocs,
  serverTimestamp,
} from "https://www.gstatic.com/firebasejs/12.19.0/firebase-firestore.js";
import {
  getStorage, ref, getDownloadURL,
} from "https://www.gstatic.com/firebasejs/12.19.0/firebase-storage.js";

const pad4 = (n) => String(n).padStart(4, "0");
export const idAnotacion = (video, frame, uid) => `${video}__${frame}__${uid}`;

export function crearBackendFirebase(firebaseConfig) {
  const app = initializeApp(firebaseConfig);
  const auth = getAuth(app);
  const db = getFirestore(app);
  const storage = getStorage(app);
  let usuario = null;

  return {
    onAuth(cb) {
      onAuthStateChanged(auth, (u) => {
        usuario = u;
        cb(u ? { uid: u.uid, email: u.email, nombre: u.displayName || u.email } : null);
      });
    },
    async login() {
      const proveedor = new GoogleAuthProvider();
      proveedor.setCustomParameters({ prompt: "select_account" });
      await signInWithPopup(auth, proveedor);
    },
    logout: () => signOut(auth),

    /** ¿Está el correo en la colección "anotadores"? */
    async estaAutorizado() {
      try {
        return (await getDoc(doc(db, "anotadores", usuario.email))).exists();
      } catch {
        return false;
      }
    },

    async listarVideos() {
      const snap = await getDocs(collection(db, "videos"));
      return snap.docs.map((d) => ({ id: d.id, ...d.data() }))
        .sort((a, b) => a.id.localeCompare(b.id));
    },

    /** URL del bloque b (imagen con `bloque` frames en una cuadrícula de `columnas`). */
    urlBloque(video, b) {
      return getDownloadURL(ref(storage, `frames/${video.id}/bloque_${pad4(b)}.webp`));
    },

    /** Mis anotaciones de un video: Map(frame -> {lineas}). */
    async misAnotaciones(video) {
      const q = query(collection(db, "anotaciones"),
        where("uid", "==", usuario.uid), where("video", "==", video.id));
      const snap = await getDocs(q);
      const m = new Map();
      snap.forEach((d) => { const a = d.data(); m.set(a.frame, { lineas: a.lineas || [] }); });
      return m;
    },

    async guardar(video, frame, lineas) {
      const id = idAnotacion(video.id, frame, usuario.uid);
      if (!lineas.length) { await deleteDoc(doc(db, "anotaciones", id)); return; }
      await setDoc(doc(db, "anotaciones", id), {
        uid: usuario.uid,
        email: usuario.email,
        nombre: usuario.displayName || usuario.email,
        video: video.id,
        frame,
        ancho: video.ancho,
        alto: video.alto,
        formato: "lineas_v2",
        lineas,
        actualizado: serverTimestamp(),
      });
    },
  };
}

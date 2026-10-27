// almacen-local.js — Datos de la app sin servidor.
//
// - Los videos y sus frames son archivos estáticos del propio sitio (carpeta frames/).
// - Las anotaciones se guardan en el navegador (localStorage) como respaldo, para no perder
//   nada al recargar. NO se envían a ningún lado: la persona las descarga en un archivo .json
//   y lo envía. Ese archivo también se puede volver a cargar para seguir trabajando.

const CLAVE = "anotador-arteria:v1";
const CLAVE_NOMBRE = "anotador-arteria:nombre";
export const FORMATO_ARCHIVO = "anotaciones_web_v1";

const ahora = () => new Date().toISOString();
const pad4 = (n) => String(n).padStart(4, "0");

function leer() {
  try {
    const d = JSON.parse(localStorage.getItem(CLAVE));
    if (d && typeof d === "object" && d.videos) return d;
  } catch { /* datos corruptos o almacenamiento bloqueado: se empieza vacío */ }
  return { videos: {}, modificado: null, descargado: null };
}

function escribir(d) {
  localStorage.setItem(CLAVE, JSON.stringify(d));   // puede lanzar si no hay espacio o está bloqueado
}

export function crearAlmacenLocal() {
  return {
    async listarVideos() {
      const r = await fetch("frames/videos.json", { cache: "no-cache" });
      if (!r.ok) throw new Error(`no se encontró frames/videos.json (HTTP ${r.status})`);
      return (await r.json()).sort((a, b) => a.id.localeCompare(b.id));
    },

    async urlBloque(video, b) {
      return `frames/${video.id}/bloque_${pad4(b)}.webp`;
    },

    /** Anotaciones guardadas en este navegador para un video: Map(frame -> {lineas}). */
    async misAnotaciones(video) {
      const frames = leer().videos[video.id]?.frames || {};
      return new Map(Object.entries(frames).map(([f, a]) => [Number(f), { lineas: a.lineas }]));
    },

    async guardar(video, frame, lineas) {
      const d = leer();
      const v = (d.videos[video.id] ??= { frames: {} });
      Object.assign(v, { nombre: video.nombre, ancho: video.ancho, alto: video.alto,
        n_frames: video.n_frames, fps: video.fps });
      if (lineas.length) v.frames[frame] = { lineas, actualizado: ahora() };
      else delete v.frames[frame];
      d.modificado = ahora();
      escribir(d);
    },

    /** ¿Hay cambios posteriores a la última descarga? */
    pendienteDescarga() {
      const d = leer();
      return Boolean(d.modificado && (!d.descargado || d.modificado > d.descargado));
    },

    resumen() {
      const d = leer();
      let frames = 0, videos = 0;
      for (const v of Object.values(d.videos)) {
        const n = Object.keys(v.frames || {}).length;
        frames += n;
        if (n) videos++;
      }
      return { frames, videos };
    },

    get nombre() { try { return localStorage.getItem(CLAVE_NOMBRE) || ""; } catch { return ""; } },
    set nombre(v) { try { localStorage.setItem(CLAVE_NOMBRE, v); } catch { /* sin almacenamiento */ } },

    /** Contenido del archivo a descargar (todas las anotaciones de este navegador). */
    exportar(nombre) {
      const d = leer();
      const videos = {};
      for (const [id, v] of Object.entries(d.videos)) {
        if (!Object.keys(v.frames || {}).length) continue;
        const frames = {};
        for (const f of Object.keys(v.frames).map(Number).sort((a, b) => a - b)) frames[f] = v.frames[f];
        videos[id] = { ...v, frames };
      }
      return {
        formato: FORMATO_ARCHIVO,
        anotador: nombre,
        exportado: ahora(),
        herramienta: location.origin + location.pathname,
        convencion: "Frames desde 0. Coordenadas en píxeles de la imagen original (centro del píxel en "
          + "valores enteros, como OpenCV). Cada línea: altura + anclas (x, dy), y_ancla = altura + dy, "
          + "interpolación PCHIP. Líneas ordenadas de arriba hacia abajo.",
        videos,
      };
    },

    marcarDescargado() {
      const d = leer();
      d.descargado = ahora();
      escribir(d);
    },

    /** Carga un archivo descargado antes. Reemplaza los frames que vengan en él. */
    importar(obj) {
      if (!obj || obj.formato !== FORMATO_ARCHIVO || typeof obj.videos !== "object") {
        throw new Error("el archivo no es un archivo de anotaciones de esta herramienta");
      }
      const d = leer();
      let n = 0;
      for (const [id, v] of Object.entries(obj.videos)) {
        const dest = (d.videos[id] ??= { frames: {} });
        for (const [f, a] of Object.entries(v.frames || {})) {
          if (!Array.isArray(a.lineas)) continue;
          dest.frames[f] = { lineas: a.lineas, actualizado: a.actualizado || ahora() };
          n++;
        }
        for (const k of ["nombre", "ancho", "alto", "n_frames", "fps"]) if (v[k] !== undefined) dest[k] = v[k];
      }
      d.modificado = ahora();
      escribir(d);
      if (obj.anotador && !this.nombre) this.nombre = obj.anotador;
      return n;
    },
  };
}

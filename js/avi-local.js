// avi-local.js — Abre un .avi de la computadora de la persona, sin subirlo a ningún lado.
//
// El navegador no reproduce .avi, pero un AVI es solo un contenedor RIFF con un fragmento por
// frame. Aquí se recorre el archivo, se anota dónde está cada frame y, cuando la página pide uno,
// se lee solo ese pedazo (File.slice) y se decodifica. Así se puede ir a cualquier frame exacto,
// sin cargar el video completo en memoria.
//
// Códecs soportados:
//   - MJPEG (lo que produce VideosDVD/recortar_vob_a_avi.py por defecto): cada frame es un JPEG.
//   - PNG (recortar_vob_a_avi.py --codec png): sin pérdida, píxeles idénticos a OpenCV.
//   - Sin compresión (BI_RGB, 24 o 32 bits).
//
// Numeración: igual que OpenCV (cv2.VideoCapture + read en orden). Los fragmentos de video de
// tamaño 0 (frames "repetidos" que escribe ffmpeg) se saltan, como hace OpenCV: el frame N de
// esta página es el N-ésimo fragmento no vacío. Verificado frame por frame contra OpenCV.

const VENTANA = 4 << 20;   // bytes leídos de una vez al recorrer el archivo

const fourcc = (dv, o) => String.fromCharCode(dv.getUint8(o), dv.getUint8(o + 1), dv.getUint8(o + 2), dv.getUint8(o + 3));

/** Lector con ventana: pide al archivo bloques grandes y responde lecturas pequeñas desde ahí. */
function crearLector(file) {
  let ini = -1, buf = null;
  return async function leer(pos, n) {
    if (!buf || pos < ini || pos + n > ini + buf.byteLength) {
      ini = pos;
      buf = await file.slice(pos, Math.min(file.size, pos + Math.max(n, VENTANA))).arrayBuffer();
    }
    return new DataView(buf, pos - ini, Math.min(n, buf.byteLength - (pos - ini)));
  };
}

/** Lee la cabecera `hdrl`: stream de video, fps, tamaño y códec. */
function leerCabecera(dv) {
  const streams = [];
  let actual = null;
  (function recorrer(o, fin) {
    while (o + 8 <= fin) {
      const id = fourcc(dv, o), tam = dv.getUint32(o + 4, true), datos = o + 8;
      if (id === "LIST") {
        if (fourcc(dv, datos) === "strl") { actual = {}; streams.push(actual); }
        recorrer(datos + 4, Math.min(fin, datos + tam));
      } else if (id === "strh" && actual) {
        actual.tipo = fourcc(dv, datos);
        actual.handler = fourcc(dv, datos + 4);
        actual.escala = dv.getUint32(datos + 20, true);
        actual.tasa = dv.getUint32(datos + 24, true);
      } else if (id === "strf" && actual && actual.tipo === "vids") {
        actual.ancho = dv.getInt32(datos + 4, true);
        actual.alto = dv.getInt32(datos + 8, true);
        actual.bits = dv.getUint16(datos + 14, true);
        actual.compresion = dv.getUint32(datos + 16, true);
        actual.compresionTxt = fourcc(dv, datos + 16);
      }
      o = datos + tam + (tam & 1);
    }
  })(0, dv.byteLength);
  const k = streams.findIndex((s) => s.tipo === "vids");
  if (k < 0) throw new Error("el AVI no tiene un stream de video");
  return { ...streams[k], indice: k };
}

/**
 * Recorre el archivo y devuelve el lector del video.
 * @param {File} file
 * @param {(fraccion:number)=>void} [progreso]
 */
export async function abrirAviLocal(file, progreso) {
  const leer = crearLector(file);
  const h0 = await leer(0, 12);
  if (h0.byteLength < 12 || fourcc(h0, 0) !== "RIFF" || fourcc(h0, 8) !== "AVI ") {
    throw new Error("no es un archivo AVI");
  }

  let cab = null;
  const frames = [];            // [offset de los datos, tamaño]
  let prefijo = null;           // "00", "01"…: número del stream de video en los fragmentos
  let vacios = 0;

  // Recorre RIFF 'AVI ' y las extensiones RIFF 'AVIX' (OpenDML, archivos > 1 GB).
  async function recorrer(o, fin) {
    while (o + 8 <= fin) {
      const dv = await leer(o, 12);
      if (dv.byteLength < 8) break;
      const id = fourcc(dv, 0), tam = dv.getUint32(4, true), datos = o + 8;
      if (id === "RIFF" || id === "LIST") {
        const tipo = dv.byteLength >= 12 ? fourcc(dv, 8) : "";
        if (tipo === "hdrl") {
          const buf = new DataView(await file.slice(datos + 4, datos + tam).arrayBuffer());
          cab = leerCabecera(buf);
          prefijo = String(cab.indice).padStart(2, "0");
        } else if (tipo !== "INFO") {
          await recorrer(datos + 4, Math.min(fin, datos + tam));
        }
      } else if (prefijo && id.startsWith(prefijo) && (id.endsWith("dc") || id.endsWith("db"))) {
        if (tam > 0) frames.push([datos, tam]); else vacios++;
        if (progreso && frames.length % 500 === 0) progreso(datos / file.size);
      }
      if (tam === 0 && id === "RIFF") break;
      o = datos + tam + (tam & 1);
    }
  }
  await recorrer(0, file.size);

  if (!cab) throw new Error("el AVI no tiene cabecera (hdrl)");
  if (!frames.length) throw new Error("el AVI no tiene frames legibles");

  const ancho = Math.abs(cab.ancho), alto = Math.abs(cab.alto);
  const sinCompresion = cab.compresion === 0;
  if (sinCompresion && cab.bits !== 24 && cab.bits !== 32) {
    throw new Error(`AVI sin compresión de ${cab.bits} bits: solo se leen 24 o 32 bits`);
  }

  async function frame(i) {
    const [o, tam] = frames[i];
    const blob = file.slice(o, o + tam);
    if (sinCompresion) return decodificarRGB(new Uint8Array(await blob.arrayBuffer()), ancho, cab.alto, cab.bits);
    const cab4 = new Uint8Array(await blob.slice(0, 4).arrayBuffer());
    let tipo;
    if (cab4[0] === 0xff && cab4[1] === 0xd8) tipo = "image/jpeg";
    else if (cab4[0] === 0x89 && cab4[1] === 0x50 && cab4[2] === 0x4e && cab4[3] === 0x47) tipo = "image/png";
    else throw new Error(`códec «${cab.compresionTxt.trim() || cab.handler}» no soportado. `
      + "Convierte el video con recortar_vob_a_avi.py (MJPEG o --codec png)");
    // colorSpaceConversion "none": los píxeles quedan tal como están en el archivo.
    return createImageBitmap(new Blob([blob], { type: tipo }),
      { colorSpaceConversion: "none", premultiplyAlpha: "none" });
  }

  // Comprueba el primer frame ahora, para avisar de un códec no soportado al abrir.
  const primero = await frame(0);
  if (primero.width !== ancho || primero.height !== alto) {
    throw new Error(`el frame mide ${primero.width}×${primero.height} y la cabecera dice ${ancho}×${alto}`);
  }

  return {
    n_frames: frames.length,
    fps: cab.escala ? cab.tasa / cab.escala : 0,
    ancho, alto,
    vacios,
    codec: sinCompresion ? "rgb" : cab.compresionTxt.trim() || cab.handler,
    frame,
  };
}

/** Frame sin compresión (BGR, filas con relleno a 4 bytes, de abajo hacia arriba si alto > 0). */
function decodificarRGB(datos, ancho, altoCab, bits) {
  const alto = Math.abs(altoCab), bpp = bits / 8;
  const fila = Math.ceil((ancho * bpp) / 4) * 4;
  const img = new ImageData(ancho, alto);
  for (let y = 0; y < alto; y++) {
    const src = (altoCab > 0 ? alto - 1 - y : y) * fila;
    for (let x = 0; x < ancho; x++) {
      const s = src + x * bpp, d = (y * ancho + x) * 4;
      img.data[d] = datos[s + 2]; img.data[d + 1] = datos[s + 1]; img.data[d + 2] = datos[s];
      img.data[d + 3] = 255;
    }
  }
  return createImageBitmap(img, { colorSpaceConversion: "none", premultiplyAlpha: "none" });
}

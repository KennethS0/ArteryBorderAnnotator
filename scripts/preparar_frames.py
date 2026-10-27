#!/usr/bin/env python3
"""
preparar_frames.py — Extrae los frames de los videos .avi, los empaqueta en bloques y
(opcionalmente) los sube a Firebase Storage y registra cada video en Firestore.

Por qué bloques: los 4 videos tienen ~15 000 frames. Subirlos sueltos excede las 5 000
subidas mensuales sin costo de Firebase Storage y hace lenta la navegación. Cada bloque
es una imagen WebP SIN PÉRDIDA con 25 frames en una cuadrícula de 5×5: los píxeles son
idénticos a los que lee OpenCV, y la web recorta la celda del frame pedido.

Los frames se leen con OpenCV en orden, igual que arteria_braquial.py y anotador_frames_v2.py,
así que el frame N de la web es exactamente el frame N de los otros programas.

Uso:
    # 1) Solo generar los bloques en disco (para revisar):
    python scripts/preparar_frames.py ../videos

    # 2) Generar y subir (necesita la clave de una cuenta de servicio, ver README):
    python scripts/preparar_frames.py ../videos --subir \
        --credenciales clave-servicio.json --bucket TU-PROYECTO.firebasestorage.app

Salida local:  frames_web/frames/<video>/bloque_0000.webp, ...  y  frames_web/videos.json
En Storage:    frames/<video>/bloque_0000.webp, ...
En Firestore:  videos/<video> = {nombre, n_frames, fps, ancho, alto, bloque, columnas, ...}
"""

import argparse
import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np


def procesar_video(ruta, salida, bloque, columnas):
    cap = cv2.VideoCapture(str(ruta))
    if not cap.isOpened():
        raise RuntimeError(f"No se pudo abrir {ruta}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    filas = math.ceil(bloque / columnas)
    vid = ruta.stem
    carpeta = salida / "frames" / vid
    carpeta.mkdir(parents=True, exist_ok=True)

    n, b, buffer, ancho, alto = 0, 0, [], None, None

    def escribir_bloque(frames, nb):
        hoja = np.zeros((filas * alto, columnas * ancho, 3), np.uint8)
        for k, f in enumerate(frames):
            r, c = divmod(k, columnas)
            hoja[r * alto:(r + 1) * alto, c * ancho:(c + 1) * ancho] = f
        ok, datos = cv2.imencode(".webp", hoja, [cv2.IMWRITE_WEBP_QUALITY, 101])   # 101 = sin pérdida
        if not ok:
            raise RuntimeError("OpenCV no pudo codificar WebP")
        (carpeta / f"bloque_{nb:04d}.webp").write_bytes(datos.tobytes())

    while True:
        ok, f = cap.read()
        if not ok:
            break
        if ancho is None:
            alto, ancho = f.shape[:2]
        buffer.append(f)
        n += 1
        if len(buffer) == bloque:
            escribir_bloque(buffer, b)
            buffer, b = [], b + 1
        if n % 500 == 0:
            print(f"  {vid}: {n} frames…", flush=True)
    if buffer:
        escribir_bloque(buffer, b)
        b += 1
    cap.release()
    if n == 0:
        raise RuntimeError(f"{ruta} no tiene frames legibles")

    return {
        "id": vid,
        "nombre": ruta.name,
        "n_frames": n,
        "fps": fps,
        "ancho": ancho,
        "alto": alto,
        "bloque": bloque,
        "columnas": columnas,
        "n_bloques": b,
        "formato": "webp-lossless",
    }


def subir(salida, metas, credenciales, bucket_nombre, hilos):
    import firebase_admin
    from firebase_admin import credentials, firestore, storage

    firebase_admin.initialize_app(credentials.Certificate(str(credenciales)),
                                  {"storageBucket": bucket_nombre})
    bucket = storage.bucket()
    db = firestore.client()

    existentes = {bl.name: bl.size for bl in bucket.list_blobs(prefix="frames/")}
    tareas = []
    for meta in metas:
        for archivo in sorted((salida / "frames" / meta["id"]).glob("bloque_*.webp")):
            nombre = f"frames/{meta['id']}/{archivo.name}"
            if existentes.get(nombre) != archivo.stat().st_size:      # ya subido igual → se salta
                tareas.append((archivo, nombre))

    def subir_uno(t):
        archivo, nombre = t
        blob = bucket.blob(nombre)
        # Los bloques no cambian: el navegador puede guardarlos en caché por mucho tiempo.
        blob.cache_control = "private, max-age=31536000, immutable"
        blob.upload_from_filename(str(archivo), content_type="image/webp")
        return nombre

    print(f"Subiendo {len(tareas)} bloques ({len(existentes)} ya estaban en Storage)…")
    with ThreadPoolExecutor(hilos) as ex:
        for i, _ in enumerate(ex.map(subir_uno, tareas), 1):
            if i % 50 == 0 or i == len(tareas):
                print(f"  {i}/{len(tareas)}", flush=True)

    for meta in metas:
        db.collection("videos").document(meta["id"]).set(meta)
        print(f"Registrado videos/{meta['id']} en Firestore ({meta['n_frames']} frames).")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("videos", nargs="+", help="archivos .avi o carpetas que los contienen")
    ap.add_argument("--salida", default="frames_web", help="carpeta local de salida (por defecto: frames_web)")
    ap.add_argument("--bloque", type=int, default=25, help="frames por bloque (por defecto: 25)")
    ap.add_argument("--columnas", type=int, default=5, help="columnas de la cuadrícula (por defecto: 5)")
    ap.add_argument("--subir", action="store_true", help="subir a Firebase Storage y registrar en Firestore")
    ap.add_argument("--credenciales", help="JSON de la cuenta de servicio de Firebase")
    ap.add_argument("--bucket", help="bucket de Storage, p. ej. TU-PROYECTO.firebasestorage.app")
    ap.add_argument("--hilos", type=int, default=8, help="subidas en paralelo (por defecto: 8)")
    args = ap.parse_args()

    if args.subir and not (args.credenciales and args.bucket):
        ap.error("--subir necesita --credenciales y --bucket")

    rutas = []
    for v in map(Path, args.videos):
        rutas += sorted(v.glob("*.avi")) if v.is_dir() else [v]
    if not rutas:
        sys.exit("No se encontraron videos .avi")

    salida = Path(args.salida)
    metas = []
    for ruta in rutas:
        print(f"Procesando {ruta.name}…")
        meta = procesar_video(ruta, salida, args.bloque, args.columnas)
        tam = sum(p.stat().st_size for p in (salida / "frames" / meta["id"]).glob("*.webp"))
        print(f"  {meta['n_frames']} frames, {meta['n_bloques']} bloques, {tam / 1e6:.1f} MB")
        metas.append(meta)

    (salida / "videos.json").write_text(json.dumps(metas, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Bloques en {salida.resolve()}")

    if args.subir:
        subir(salida, metas, args.credenciales, args.bucket, args.hilos)


if __name__ == "__main__":
    main()

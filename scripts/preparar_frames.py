#!/usr/bin/env python3
"""
preparar_frames.py — Extrae los frames de los videos .avi y los empaqueta para la web.

Cada bloque es una imagen WebP SIN PÉRDIDA con 25 frames en una cuadrícula de 5×5: los
píxeles son idénticos a los que lee OpenCV, y la web recorta la celda del frame pedido.
Así son ~150 archivos por video en lugar de ~3 700, y navegar es rápido.

Los frames se leen con OpenCV en orden, igual que arteria_braquial.py y anotador_frames_v2.py,
así que el frame N de la web es exactamente el frame N de los otros programas.

Uso (desde la raíz del repositorio):
    python scripts/preparar_frames.py ../videos
    python scripts/preparar_frames.py ../videos/VTS_01_6.avi        # agregar un video

Escribe:  frames/<video>/bloque_0000.webp, ...   y   frames/videos.json  (lista de videos)
Después: git add frames && git commit && git push
"""

import argparse
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

RAIZ = Path(__file__).resolve().parent.parent


def procesar_video(ruta, carpeta_frames, bloque, columnas):
    cap = cv2.VideoCapture(str(ruta))
    if not cap.isOpened():
        raise RuntimeError(f"No se pudo abrir {ruta}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    filas = math.ceil(bloque / columnas)
    vid = ruta.stem
    carpeta = carpeta_frames / vid
    carpeta.mkdir(parents=True, exist_ok=True)
    for viejo in carpeta.glob("bloque_*.webp"):
        viejo.unlink()

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

    return {"id": vid, "nombre": ruta.name, "n_frames": n, "fps": fps, "ancho": ancho, "alto": alto,
            "bloque": bloque, "columnas": columnas, "n_bloques": b, "formato": "webp-lossless"}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("videos", nargs="+", help="archivos .avi o carpetas que los contienen")
    ap.add_argument("--salida", default=str(RAIZ / "frames"), help="carpeta frames/ del sitio (por defecto: la del repo)")
    ap.add_argument("--bloque", type=int, default=25, help="frames por bloque (por defecto: 25)")
    ap.add_argument("--columnas", type=int, default=5, help="columnas de la cuadrícula (por defecto: 5)")
    args = ap.parse_args()

    rutas = []
    for v in map(Path, args.videos):
        rutas += sorted(v.glob("*.avi")) if v.is_dir() else [v]
    if not rutas:
        sys.exit("No se encontraron videos .avi")

    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)
    ruta_lista = salida / "videos.json"
    metas = {m["id"]: m for m in json.loads(ruta_lista.read_text(encoding="utf-8"))} if ruta_lista.exists() else {}

    for ruta in rutas:
        print(f"Procesando {ruta.name}…")
        meta = procesar_video(ruta, salida, args.bloque, args.columnas)
        tam = sum(p.stat().st_size for p in (salida / meta["id"]).glob("*.webp"))
        print(f"  {meta['n_frames']} frames, {meta['n_bloques']} bloques, {tam / 1e6:.1f} MB")
        metas[meta["id"]] = meta

    lista = sorted(metas.values(), key=lambda m: m["id"])
    ruta_lista.write_text(json.dumps(lista, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Listo: {len(lista)} video(s) en {ruta_lista}")


if __name__ == "__main__":
    main()

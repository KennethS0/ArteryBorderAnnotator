#!/usr/bin/env python3
"""
descargar_anotaciones.py — Baja de Firestore las anotaciones hechas en la web y las escribe
en el mismo formato que exporta la herramienta de escritorio (anotador_frames_v2.py).

Por cada anotación (video, frame, persona):
    <salida>/<video>_ground_truth/<persona>/<frame>/
        frame_<n>.json            mismo formato "lineas_v2" + quién anotó y cuándo
        frame_<n>_original.png    el frame leído del .avi original con OpenCV
        frame_<n>_anotado.png     el frame con las curvas dibujadas

Y un resumen con una fila por anotación:
    <salida>/resumen_anotaciones.csv   (video, frame, persona, diámetro medio/mediana/mín/máx…)
Ese CSV sirve para comparar con arteria_braquial.py y entre anotadores.

Uso:
    python scripts/descargar_anotaciones.py --credenciales clave-servicio.json --videos ../videos
    python scripts/descargar_anotaciones.py --credenciales clave-servicio.json --sin-imagenes
"""

import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

from formato_ground_truth import distancias_consecutivas, exportar_frame, orden_vertical


def nombre_persona(email):
    """Carpeta legible y segura a partir del correo (parte antes de la @)."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", (email or "desconocido").split("@")[0])


def a_lineas(doc):
    """Firestore guarda las anclas como [{x, dy}]; el formato interno es [[x, dy]]."""
    lineas = []
    for l in doc.get("lineas", []):
        anclas = sorted([float(a["x"]), float(a["dy"])] for a in l.get("anclas", []))
        if len(anclas) >= 2:
            lineas.append({"altura": float(l["altura"]), "anclas": anclas})
    return lineas


def leer_frames(ruta, indices):
    """Lee los frames pedidos recorriendo el video en orden (mismo índice que OpenCV/escritorio)."""
    pedidos, frames = set(indices), {}
    if not pedidos:
        return frames
    cap = cv2.VideoCapture(str(ruta))
    ultimo, i = max(pedidos), 0
    while i <= ultimo:
        ok, f = cap.read()
        if not ok:
            break
        if i in pedidos:
            frames[i] = f
        i += 1
    cap.release()
    return frames


def procesar(docs, videos_dir, salida, meta_videos, con_imagenes):
    salida = Path(salida)
    por_video = defaultdict(list)
    for d in docs:
        por_video[d["video"]].append(d)

    filas = []
    for vid, lista in sorted(por_video.items()):
        meta = meta_videos.get(vid, {})
        fps = meta.get("fps") or 0.0
        ruta = Path(videos_dir) / f"{vid}.avi" if videos_dir else None
        frames = {}
        if con_imagenes:
            if ruta is None or not ruta.exists():
                print(f"[aviso] No encontré {vid}.avi en {videos_dir}; para {vid} solo se escribe el CSV.")
            else:
                frames = leer_frames(ruta, [d["frame"] for d in lista])
        n_escritos = 0
        for d in sorted(lista, key=lambda x: (x["frame"], x.get("email", ""))):
            lineas = a_lineas(d)
            persona = nombre_persona(d.get("email"))
            actualizado = d.get("actualizado")
            actualizado = actualizado.isoformat() if hasattr(actualizado, "isoformat") else actualizado
            pares = distancias_consecutivas([lineas[i] for i in orden_vertical(lineas)]) if lineas else []
            fila = {
                "video": vid, "frame": d["frame"],
                "tiempo_s": round(d["frame"] / fps, 4) if fps else "",
                "persona": persona, "email": d.get("email", ""), "n_lineas": len(lineas),
                "diametro_medio_px": "", "diametro_mediana_px": "", "diametro_min_px": "",
                "diametro_max_px": "", "diametro_desv_px": "", "x_inicio": "", "x_fin": "",
                "actualizado": actualizado or "",
            }
            if len(lineas) == 2 and pares:
                _, _, cols, dist = pares[0]
                fila.update({
                    "diametro_medio_px": round(float(np.mean(dist)), 3),
                    "diametro_mediana_px": round(float(np.median(dist)), 3),
                    "diametro_min_px": round(float(np.min(dist)), 3),
                    "diametro_max_px": round(float(np.max(dist)), 3),
                    "diametro_desv_px": round(float(np.std(dist)), 3),
                    "x_inicio": int(cols[0]), "x_fin": int(cols[-1]),
                })
            filas.append(fila)

            if d["frame"] in frames and lineas:
                exportar_frame(
                    frames[d["frame"]], lineas,
                    salida / f"{vid}_ground_truth" / persona / str(d["frame"]),
                    video_nombre=f"{vid}.avi", ruta_video=ruta.resolve(), frame=d["frame"], fps=fps,
                    extra={"anotador": {"email": d.get("email"), "nombre": d.get("nombre"), "uid": d.get("uid")},
                           "actualizado_web": actualizado, "origen": "web"},
                )
                n_escritos += 1
        print(f"{vid}: {len(lista)} anotaciones" + (f", {n_escritos} exportadas con imágenes" if con_imagenes else ""))

    salida.mkdir(parents=True, exist_ok=True)
    ruta_csv = salida / "resumen_anotaciones.csv"
    campos = ["video", "frame", "tiempo_s", "persona", "email", "n_lineas", "diametro_medio_px",
              "diametro_mediana_px", "diametro_min_px", "diametro_max_px", "diametro_desv_px",
              "x_inicio", "x_fin", "actualizado"]
    with ruta_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=campos)
        w.writeheader()
        w.writerows(filas)
    print(f"Resumen: {ruta_csv.resolve()} ({len(filas)} filas)")
    return filas


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--credenciales", required=True, help="JSON de la cuenta de servicio de Firebase")
    ap.add_argument("--videos", default="../videos", help="carpeta con los .avi originales (por defecto: ../videos)")
    ap.add_argument("--salida", default="ground_truth_web", help="carpeta de salida (por defecto: ground_truth_web)")
    ap.add_argument("--sin-imagenes", action="store_true", help="solo el CSV de resumen, sin JSON/PNG por frame")
    args = ap.parse_args()

    import firebase_admin
    from firebase_admin import credentials, firestore

    firebase_admin.initialize_app(credentials.Certificate(args.credenciales))
    db = firestore.client()
    meta_videos = {d.id: d.to_dict() for d in db.collection("videos").stream()}
    docs = [d.to_dict() for d in db.collection("anotaciones").stream()]
    print(f"{len(docs)} anotaciones en Firestore.")
    procesar(docs, args.videos, args.salida, meta_videos, not args.sin_imagenes)


if __name__ == "__main__":
    main()

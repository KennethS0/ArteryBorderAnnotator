#!/usr/bin/env python3
"""
importar_anotaciones.py — Convierte los archivos que envían los anotadores
(anotaciones_<nombre>_<fecha>.json, descargados de la web) al mismo formato que exporta la
herramienta de escritorio (anotador_frames_v2.py).

Cada frame viene anotado con 2 líneas o con pares de puntos verticales (mínimo 10; los frames
con menos se omiten con un aviso). Por cada anotación (video, frame, persona):
    <salida>/<video>_ground_truth/<persona>/<frame>/
        frame_<n>.json            formato "lineas_v2" (líneas) o "pares_v1" (puntos) + quién anotó
        frame_<n>_original.png    el frame leído del .avi original con OpenCV
        frame_<n>_anotado.png     el frame con las curvas dibujadas

Y un resumen con una fila por anotación:
    <salida>/resumen_anotaciones.csv   (video, frame, persona, diámetro medio/mediana/mín/máx…)
Ese CSV sirve para comparar con arteria_braquial.py y entre anotadores.

Si llegan varios archivos de la misma persona, por cada frame se queda la versión editada más
recientemente.

Uso (desde la raíz del repositorio):
    python scripts/importar_anotaciones.py recibidos/            # una carpeta con los .json
    python scripts/importar_anotaciones.py a.json b.json --videos ../videos --salida ground_truth_web
    python scripts/importar_anotaciones.py recibidos/ --sin-imagenes   # solo el CSV
"""

import argparse
import csv
import json
import re
import sys
import unicodedata
from pathlib import Path

import numpy as np

from formato_ground_truth import distancias_consecutivas, exportar_frame, exportar_frame_pares, orden_vertical

FORMATO = "anotaciones_web_v1"
MIN_PARES = 10


def nombre_carpeta(texto):
    """'María José Pérez' -> 'maria_jose_perez'."""
    t = unicodedata.normalize("NFD", texto or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "_", t).strip("_").lower() or "anotador"


def a_lineas(lineas_json):
    """La web guarda las anclas como [{x, dy}]; el formato interno es [[x, dy]]."""
    lineas = []
    for l in lineas_json or []:
        anclas = sorted([float(a["x"]), float(a["dy"])] for a in l.get("anclas", []))
        if len(anclas) >= 2:
            lineas.append({"altura": float(l["altura"]), "anclas": anclas})
    return lineas


def leer_archivos(rutas):
    """{(video, frame, persona): {...}} con la versión más reciente de cada anotación."""
    anotaciones, metas = {}, {}
    for ruta in rutas:
        try:
            datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"[aviso] {ruta}: no se pudo leer ({exc}); se omite.")
            continue
        if datos.get("formato") != FORMATO:
            print(f"[aviso] {ruta}: no es un archivo de anotaciones de la web; se omite.")
            continue
        anotador = datos.get("anotador") or Path(ruta).stem
        persona = nombre_carpeta(anotador)
        n = 0
        for vid, v in (datos.get("videos") or {}).items():
            metas.setdefault(vid, {}).update({k: v[k] for k in ("fps", "ancho", "alto", "n_frames") if k in v})
            for f, a in (v.get("frames") or {}).items():
                clave = (vid, int(f), persona)
                actual = anotaciones.get(clave)
                if actual is None or (a.get("actualizado") or "") >= (actual["actualizado"] or ""):
                    pares = sorted((float(q["x"]), min(float(q["y_superior"]), float(q["y_inferior"])),
                                    max(float(q["y_superior"]), float(q["y_inferior"])))
                                   for q in a.get("pares") or [])
                    anotaciones[clave] = {"lineas": a_lineas(a.get("lineas")), "pares": pares, "anotador": anotador,
                                          "actualizado": a.get("actualizado"), "archivo": Path(ruta).name}
                n += 1
        print(f"{Path(ruta).name}: {anotador}, {n} frames")
    return anotaciones, metas


def leer_frames(ruta, indices):
    """Lee los frames pedidos recorriendo el video en orden (mismo índice que OpenCV/escritorio)."""
    import cv2
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


def procesar(anotaciones, metas, videos_dir, salida, con_imagenes, min_pares=MIN_PARES):
    salida = Path(salida)
    for k in sorted(anotaciones):
        n = len(anotaciones[k]["pares"])
        if n and n < min_pares:
            print(f"[aviso] {k[0]} frame {k[1]} ({anotaciones[k]['anotador']}): {n} pares de puntos "
                  f"(mínimo {min_pares}); se omite.")
            del anotaciones[k]
    salida.mkdir(parents=True, exist_ok=True)
    filas = []
    for vid in sorted({k[0] for k in anotaciones}):
        claves = sorted(k for k in anotaciones if k[0] == vid)
        fps = metas.get(vid, {}).get("fps") or 0.0
        ruta = Path(videos_dir) / f"{vid}.avi"
        frames = {}
        if con_imagenes:
            if ruta.exists():
                frames = leer_frames(ruta, [k[1] for k in claves])
            else:
                print(f"[aviso] No encontré {ruta}; para {vid} solo se escribe el CSV.")
        escritos = 0
        for (_, frame, persona) in claves:
            a = anotaciones[(vid, frame, persona)]
            lineas = a["lineas"]
            pares = a["pares"]
            ordenadas = [lineas[i] for i in orden_vertical(lineas)] if lineas else []
            pares_lineas = distancias_consecutivas(ordenadas) if ordenadas else []
            fila = {"video": vid, "frame": frame, "tiempo_s": round(frame / fps, 4) if fps else "",
                    "persona": persona, "anotador": a["anotador"], "tipo": "pares" if pares else "lineas",
                    "n_lineas": len(lineas), "n_pares": len(pares),
                    "diametro_medio_px": "", "diametro_mediana_px": "", "diametro_min_px": "",
                    "diametro_max_px": "", "diametro_desv_px": "", "x_inicio": "", "x_fin": "",
                    "actualizado": a["actualizado"] or "", "archivo": a["archivo"]}
            if len(a["pares"]):
                d = np.array([yi - ys for _, ys, yi in a["pares"]])
                fila.update({"diametro_medio_px": round(float(np.mean(d)), 3),
                             "diametro_mediana_px": round(float(np.median(d)), 3),
                             "diametro_min_px": round(float(np.min(d)), 3),
                             "diametro_max_px": round(float(np.max(d)), 3),
                             "diametro_desv_px": round(float(np.std(d)), 3),
                             "x_inicio": round(a["pares"][0][0], 2), "x_fin": round(a["pares"][-1][0], 2)})
            elif len(lineas) == 2 and pares_lineas:
                _, _, cols, d = pares_lineas[0]
                fila.update({"diametro_medio_px": round(float(np.mean(d)), 3),
                             "diametro_mediana_px": round(float(np.median(d)), 3),
                             "diametro_min_px": round(float(np.min(d)), 3),
                             "diametro_max_px": round(float(np.max(d)), 3),
                             "diametro_desv_px": round(float(np.std(d)), 3),
                             "x_inicio": int(cols[0]), "x_fin": int(cols[-1])})
            filas.append(fila)
            extra = {"anotador": a["anotador"], "actualizado_web": a["actualizado"],
                     "archivo_origen": a["archivo"], "origen": "web"}
            if frame in frames and pares:
                exportar_frame_pares(frames[frame], pares, salida / f"{vid}_ground_truth" / persona / str(frame),
                                     video_nombre=f"{vid}.avi", ruta_video=ruta.resolve(), frame=frame, fps=fps,
                                     extra=extra)
                escritos += 1
            elif frame in frames and lineas:
                exportar_frame(frames[frame], lineas, salida / f"{vid}_ground_truth" / persona / str(frame),
                               video_nombre=f"{vid}.avi", ruta_video=ruta.resolve(), frame=frame, fps=fps,
                               extra={"anotador": a["anotador"], "actualizado_web": a["actualizado"],
                                      "archivo_origen": a["archivo"], "origen": "web"})
                escritos += 1
        print(f"{vid}: {len(claves)} anotaciones" + (f", {escritos} exportadas con imágenes" if con_imagenes else ""))

    campos = ["video", "frame", "tiempo_s", "persona", "anotador", "tipo", "n_lineas", "n_pares", "diametro_medio_px",
              "diametro_mediana_px", "diametro_min_px", "diametro_max_px", "diametro_desv_px",
              "x_inicio", "x_fin", "actualizado", "archivo"]
    ruta_csv = salida / "resumen_anotaciones.csv"
    with ruta_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=campos)
        w.writeheader()
        w.writerows(filas)
    print(f"Resumen: {ruta_csv.resolve()} ({len(filas)} filas)")
    return filas


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("entradas", nargs="+", help="archivos .json recibidos o carpetas que los contienen")
    ap.add_argument("--videos", default="../videos", help="carpeta con los .avi originales (por defecto: ../videos)")
    ap.add_argument("--salida", default="ground_truth_web", help="carpeta de salida (por defecto: ground_truth_web)")
    ap.add_argument("--sin-imagenes", action="store_true", help="solo el CSV de resumen, sin JSON/PNG por frame")
    args = ap.parse_args()

    rutas = []
    for e in map(Path, args.entradas):
        rutas += sorted(e.glob("*.json")) if e.is_dir() else [e]
    if not rutas:
        sys.exit("No se encontraron archivos .json")
    anotaciones, metas = leer_archivos(rutas)
    if not anotaciones:
        sys.exit("Los archivos no tienen anotaciones.")
    procesar(anotaciones, metas, args.videos, args.salida, not args.sin_imagenes)


if __name__ == "__main__":
    main()

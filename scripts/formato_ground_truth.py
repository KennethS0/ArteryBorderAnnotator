"""
formato_ground_truth.py — Geometría de las líneas y exportación en el formato "lineas_v2".

Es el mismo código de ground_truth/anotador_frames_v2.py (PCHIP, distancias por columna y
exportación), separado de la interfaz para que los scripts produzcan exactamente los mismos
archivos que la herramienta de escritorio.

Modelo: linea = {"altura": float, "anclas": [[x, dy], ...]}   (anclas ordenadas por x)
        y_ancla = altura + dy
"""

import json
import math
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

COLORES = [(0, 255, 0), (255, 80, 80), (80, 170, 255), (255, 210, 0), (255, 0, 255), (0, 255, 255)]


def _pchip_pendiente_extremo(h0, h1, m0, m1):
    d = ((2 * h0 + h1) * m0 - h0 * m1) / (h0 + h1)
    if np.sign(d) != np.sign(m0):
        return 0.0
    if np.sign(m0) != np.sign(m1) and abs(d) > abs(3 * m0):
        return 3 * m0
    return d


def pchip(xk, yk, xq):
    """Hermite cúbico monótono (Fritsch–Carlson) = scipy.interpolate.PchipInterpolator."""
    xk = np.asarray(xk, float)
    yk = np.asarray(yk, float)
    xq = np.clip(np.asarray(xq, float), xk[0], xk[-1])
    n = len(xk)
    if n == 1:
        return np.full_like(xq, yk[0])
    h = np.diff(xk)
    m = np.diff(yk) / h
    if n == 2:
        return yk[0] + m[0] * (xq - xk[0])
    d = np.zeros(n)
    w1 = 2 * h[1:] + h[:-1]
    w2 = h[1:] + 2 * h[:-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        d_int = (w1 + w2) / (w1 / m[:-1] + w2 / m[1:])
    d[1:-1] = np.where(m[:-1] * m[1:] > 0, d_int, 0.0)
    d[0] = _pchip_pendiente_extremo(h[0], h[1], m[0], m[1])
    d[-1] = _pchip_pendiente_extremo(h[-1], h[-2], m[-1], m[-2])
    i = np.clip(np.searchsorted(xk, xq, side="right") - 1, 0, n - 2)
    t = (xq - xk[i]) / h[i]
    t2, t3 = t * t, t * t * t
    return ((2 * t3 - 3 * t2 + 1) * yk[i] + (t3 - 2 * t2 + t) * h[i] * d[i]
            + (-2 * t3 + 3 * t2) * yk[i + 1] + (t3 - t2) * h[i] * d[i + 1])


def linea_y(linea, xs):
    a = np.asarray(linea["anclas"], float)
    return pchip(a[:, 0], linea["altura"] + a[:, 1], xs)


def linea_rango(linea):
    return linea["anclas"][0][0], linea["anclas"][-1][0]


def linea_y_media(linea):
    x0, x1 = linea_rango(linea)
    return float(np.mean(linea_y(linea, np.linspace(x0, x1, 64))))


def orden_vertical(lineas):
    return sorted(range(len(lineas)), key=lambda i: linea_y_media(lineas[i]))


def distancias_entre(arriba, abajo):
    x0 = max(linea_rango(arriba)[0], linea_rango(abajo)[0])
    x1 = min(linea_rango(arriba)[1], linea_rango(abajo)[1])
    cols = np.arange(math.ceil(x0), math.floor(x1) + 1)
    if len(cols) == 0:
        return None
    return cols, linea_y(abajo, cols) - linea_y(arriba, cols)


def distancias_consecutivas(lineas):
    orden = orden_vertical(lineas)
    pares = []
    for a, b in zip(orden, orden[1:]):
        res = distancias_entre(lineas[a], lineas[b])
        if res is not None:
            pares.append((a, b, *res))
    return pares


def exportar_frame(frame_bgr, lineas, carpeta, *, video_nombre, ruta_video, frame, fps, extra=None):
    """Escribe frame_<n>_original.png, frame_<n>_anotado.png y frame_<n>.json en `carpeta`.

    Mismo contenido que el botón Exportar de anotador_frames_v2.py; `extra` agrega campos
    al JSON (p. ej. quién anotó). Devuelve el diccionario escrito en el JSON.
    """
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    idx = frame
    ordenadas = [lineas[i] for i in orden_vertical(lineas)]
    anotada = frame_bgr.copy()
    S = 16
    lineas_json = []
    for k, linea in enumerate(ordenadas):
        r, g, b = COLORES[k % len(COLORES)]
        col = (b, g, r)
        x0, x1 = linea_rango(linea)
        xs = np.linspace(x0, x1, max(2, int((x1 - x0) * 4) + 1))
        ys = linea_y(linea, xs)
        pts = np.round(np.stack([xs, ys], axis=1) * S).astype(np.int32)
        cv2.polylines(anotada, [pts], False, col, 1, cv2.LINE_AA, shift=4)
        for x, dy in linea["anclas"]:
            y = linea["altura"] + dy
            cv2.circle(anotada, (int(round(x * S)), int(round(y * S))), 2 * S, col, 1, cv2.LINE_AA, shift=4)
        pos = ((int(x0) - 18, int(round(ys[0])) + 4) if x0 >= 20
               else (int(x0) + 4, int(round(ys[0])) - 5))
        cv2.putText(anotada, f"L{k + 1}", pos, cv2.FONT_HERSHEY_SIMPLEX, 0.35, col, 1, cv2.LINE_AA)
        cols = np.arange(math.ceil(x0), math.floor(x1) + 1)
        lineas_json.append({
            "id": k + 1,
            "altura": round(linea["altura"], 2),
            "anclas": [{"x": round(x, 2), "dy": round(dy, 2), "y": round(linea["altura"] + dy, 2)}
                       for x, dy in linea["anclas"]],
            "curva_por_columna": {"x": cols.tolist(),
                                  "y": [round(float(v), 2) for v in linea_y(linea, cols)]},
        })

    distancias_json = []
    for a, b, cols, d in distancias_consecutivas(ordenadas):
        xm = float(cols[len(cols) // 2])
        ya, yb = linea_y(ordenadas[a], [xm])[0], linea_y(ordenadas[b], [xm])[0]
        cv2.line(anotada, (int(round(xm * S)), int(round(ya * S))),
                 (int(round(xm * S)), int(round(yb * S))), (255, 255, 255), 1, cv2.LINE_AA, shift=4)
        media = float(np.mean(d))
        cv2.putText(anotada, f"{media:.1f}px", (int(xm) + 4, int((ya + yb) / 2) + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1, cv2.LINE_AA)
        distancias_json.append({
            "lineas": [a + 1, b + 1], "x_inicio": int(cols[0]), "x_fin": int(cols[-1]),
            "n_columnas": int(len(cols)), "media_px": round(media, 3),
            "mediana_px": round(float(np.median(d)), 3), "min_px": round(float(np.min(d)), 3),
            "max_px": round(float(np.max(d)), 3), "desv_px": round(float(np.std(d)), 3),
            "por_columna": [round(float(v), 2) for v in d],
        })

    h, w = frame_bgr.shape[:2]
    datos = {
        "video": video_nombre,
        "ruta_video": str(ruta_video),
        "frame": idx,
        "tiempo_s": round(idx / fps, 4) if fps else None,
        "fps": fps,
        "ancho_px": w,
        "alto_px": h,
        "unidades": "px",
        "formato": "lineas_v2",
        "convencion": "Frames desde 0. Coordenadas en píxeles de la imagen original; el centro de "
                      "cada píxel está en valores enteros (OpenCV). Cada línea se define por "
                      "'altura' y 'anclas' (x, dy), con y_ancla = altura + dy; la curva pasa por "
                      "las anclas y se interpola con PCHIP (scipy.interpolate.PchipInterpolator). "
                      "'y' de cada ancla, 'curva_por_columna' y 'distancias' son derivados. "
                      "Las líneas van numeradas de arriba hacia abajo. Distancias verticales.",
        "interpolacion": "pchip",
        "n_lineas": len(lineas_json),
        "lineas": lineas_json,
        "distancias": distancias_json,
        "diametro_medio_px": distancias_json[0]["media_px"] if len(lineas_json) == 2 and distancias_json else None,
        "exportado": datetime.now().isoformat(timespec="seconds"),
    }
    if extra:
        datos.update(extra)

    cv2.imwrite(str(carpeta / f"frame_{idx}_original.png"), frame_bgr)
    cv2.imwrite(str(carpeta / f"frame_{idx}_anotado.png"), anotada)
    (carpeta / f"frame_{idx}.json").write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")
    return datos

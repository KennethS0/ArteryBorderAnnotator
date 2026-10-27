#!/usr/bin/env python3
"""
lineas_anotadas.py — Reconstruye numéricamente las líneas anotadas (las paredes de la arteria)
a partir de los archivos que exporta la página web, para compararlas con las paredes detectadas.

Cada línea se guarda como "altura" + anclas (x, dy). La curva pasa por todas las anclas
(y_ancla = altura + dy) y entre ellas se interpola con PCHIP. Es exactamente el mismo cálculo
que hace la página (js/geometria.js) para dibujarla, así que los valores que da este script son
los mismos puntos que se ven en pantalla.

Las paredes salen en la misma forma que las de deteccion_bordes.py / arteria_braquial.py:
un arreglo con un valor por columna x = 0 … ancho-1 (la fila de la pared, en px, con decimales)
y NaN fuera del tramo anotado.

Uso como módulo (p. ej. desde el notebook):

    from lineas_anotadas import cargar_anotaciones, comparar_paredes

    anotaciones = cargar_anotaciones("recibidos/")          # archivos .json o carpetas
    a = anotaciones[0]
    print(a.video, a.frame, a.anotador)
    sup, inf = a.paredes()                                   # arreglos de largo a.ancho
    diam = a.diametro()                                      # inf - sup por columna

    sup_det, inf_det = buscar_paredes(...)                   # tu detección del mismo frame
    m = comparar_paredes(a, sup_det, inf_det)
    print(m["superior"]["mae_px"], m["diametro"]["sesgo_px"])

Uso desde la terminal:

    python lineas_anotadas.py recibidos/                     # -> paredes_anotadas.csv
    python lineas_anotadas.py recibidos/ --imagenes verificacion --videos ../videos

    --imagenes dibuja cada anotación sobre su frame, ampliada como en la página, para
    compararla a ojo con lo que se ve en la web.

Acepta tanto los archivos de la web (anotaciones_<nombre>_<fecha>.json) como los frame_<n>.json
que exporta la herramienta de escritorio (anotador_frames_v2.py).
"""

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

FORMATO_WEB = "anotaciones_web_v1"


# =============================================================================
# Interpolación: idéntica a js/geometria.js y a anotador_frames_v2.py
# =============================================================================
def _pendiente_extremo(h0, h1, m0, m1):
    d = ((2 * h0 + h1) * m0 - h0 * m1) / (h0 + h1)
    if np.sign(d) != np.sign(m0):
        return 0.0
    if np.sign(m0) != np.sign(m1) and abs(d) > abs(3 * m0):
        return 3 * m0
    return d


def pchip(xk, yk, xq):
    """Hermite cúbico monótono (Fritsch–Carlson) = scipy.interpolate.PchipInterpolator.

    Pasa exactamente por (xk, yk) y nunca se sale del rango de dos anclas vecinas.
    Fuera de [xk[0], xk[-1]] mantiene el valor del extremo (quien llama decide si usarlo).
    """
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
    d[0] = _pendiente_extremo(h[0], h[1], m[0], m[1])
    d[-1] = _pendiente_extremo(h[-1], h[-2], m[-1], m[-2])
    i = np.clip(np.searchsorted(xk, xq, side="right") - 1, 0, n - 2)
    t = (xq - xk[i]) / h[i]
    t2, t3 = t * t, t * t * t
    return ((2 * t3 - 3 * t2 + 1) * yk[i] + (t3 - 2 * t2 + t) * h[i] * d[i]
            + (-2 * t3 + 3 * t2) * yk[i + 1] + (t3 - t2) * h[i] * d[i + 1])


# =============================================================================
# Modelo
# =============================================================================
@dataclass
class Linea:
    altura: float
    anclas: np.ndarray            # (n, 2): columnas x, dy — ordenadas por x

    @property
    def x_anclas(self):
        return self.anclas[:, 0]

    @property
    def y_anclas(self):
        """Fila de cada ancla: y = altura + dy (el punto que se ve en la página)."""
        return self.altura + self.anclas[:, 1]

    @property
    def x_inicio(self):
        return float(self.anclas[0, 0])

    @property
    def x_fin(self):
        return float(self.anclas[-1, 0])

    def y(self, x):
        """Fila de la curva en las posiciones x (escalar o arreglo). NaN fuera del tramo."""
        x = np.asarray(x, float)
        y = pchip(self.x_anclas, self.y_anclas, x)
        return np.where((x >= self.x_inicio) & (x <= self.x_fin), y, np.nan)

    def por_columna(self, ancho):
        """Arreglo de largo `ancho`: fila de la curva en cada columna entera; NaN fuera del tramo."""
        return self.y(np.arange(ancho))

    def y_media(self):
        return float(np.mean(pchip(self.x_anclas, self.y_anclas, np.linspace(self.x_inicio, self.x_fin, 64))))


@dataclass
class Anotacion:
    video: str
    frame: int
    anotador: str
    ancho: int
    alto: int
    lineas: list                  # [Linea], ordenadas de arriba hacia abajo
    fps: float = 0.0
    actualizado: str = ""
    archivo: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def tiempo_s(self):
        return self.frame / self.fps if self.fps else None

    def paredes(self):
        """(pared_superior, pared_inferior): arreglos de largo `ancho`, NaN fuera del tramo anotado.

        Requiere exactamente 2 líneas (la de arriba es la pared superior)."""
        if len(self.lineas) != 2:
            raise ValueError(f"{self.video} frame {self.frame} ({self.anotador}): tiene {len(self.lineas)} "
                             "línea(s); para las paredes se necesitan exactamente 2")
        return self.lineas[0].por_columna(self.ancho), self.lineas[1].por_columna(self.ancho)

    def diametro(self):
        """Distancia vertical por columna (pared inferior − superior); NaN donde no se solapan."""
        sup, inf = self.paredes()
        return inf - sup

    def resumen(self):
        d = self.diametro()
        ok = ~np.isnan(d)
        if not ok.any():
            return {"n_columnas": 0}
        cols = np.flatnonzero(ok)
        return {"n_columnas": int(ok.sum()), "x_inicio": int(cols[0]), "x_fin": int(cols[-1]),
                "diametro_medio_px": float(np.mean(d[ok])), "diametro_mediana_px": float(np.median(d[ok])),
                "diametro_min_px": float(np.min(d[ok])), "diametro_max_px": float(np.max(d[ok])),
                "diametro_desv_px": float(np.std(d[ok]))}


# =============================================================================
# Lectura de archivos
# =============================================================================
def _linea_desde_json(l):
    anclas = sorted((float(a["x"]), float(a["dy"])) for a in l.get("anclas", []))
    if len(anclas) < 2:
        return None
    return Linea(altura=float(l["altura"]), anclas=np.array(anclas, float))


def _ordenar(lineas):
    return sorted([l for l in lineas if l is not None], key=Linea.y_media)


def leer_archivo(ruta):
    """Lista de Anotacion de un archivo (formato web o frame_<n>.json de escritorio)."""
    ruta = Path(ruta)
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    salida = []
    if datos.get("formato") == FORMATO_WEB:
        anotador = datos.get("anotador") or ruta.stem
        for vid, v in (datos.get("videos") or {}).items():
            for f, a in (v.get("frames") or {}).items():
                lineas = _ordenar(_linea_desde_json(l) for l in a.get("lineas", []))
                if lineas:
                    salida.append(Anotacion(video=vid, frame=int(f), anotador=anotador,
                                            ancho=int(v.get("ancho", 0)), alto=int(v.get("alto", 0)),
                                            fps=float(v.get("fps") or 0), lineas=lineas,
                                            actualizado=a.get("actualizado") or "", archivo=ruta.name))
    elif datos.get("formato") == "lineas_v2" or ("lineas" in datos and "frame" in datos):
        lineas = _ordenar(_linea_desde_json(l) for l in datos.get("lineas", []))
        anotador = datos.get("anotador")
        if isinstance(anotador, dict):
            anotador = anotador.get("nombre") or anotador.get("email")
        if lineas:
            salida.append(Anotacion(video=Path(datos.get("video", "")).stem, frame=int(datos["frame"]),
                                    anotador=anotador or "escritorio",
                                    ancho=int(datos.get("ancho_px", 0)), alto=int(datos.get("alto_px", 0)),
                                    fps=float(datos.get("fps") or 0), lineas=lineas,
                                    actualizado=datos.get("exportado", ""), archivo=ruta.name))
    else:
        raise ValueError(f"{ruta.name}: no es un archivo de anotaciones reconocido")
    for a in salida:
        if not a.ancho:
            raise ValueError(f"{ruta.name}: falta el ancho de la imagen del video {a.video}")
    return salida


def cargar_anotaciones(*entradas, ultima_version=True):
    """Lee archivos .json y/o carpetas. Devuelve una lista de Anotacion ordenada por
    (video, frame, anotador). Si la misma persona anotó un frame en varios archivos, se queda con
    la versión editada más recientemente (ultima_version=True)."""
    rutas = []
    for e in entradas:
        for p in ([e] if isinstance(e, (str, Path)) else e):
            p = Path(p)
            rutas += sorted(p.rglob("*.json")) if p.is_dir() else [p]
    todas = []
    for r in rutas:
        try:
            todas += leer_archivo(r)
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            print(f"[aviso] {r}: {exc}", file=sys.stderr)
    if ultima_version:
        unicas = {}
        for a in todas:
            k = (a.video, a.frame, a.anotador)
            if k not in unicas or a.actualizado >= unicas[k].actualizado:
                unicas[k] = a
        todas = list(unicas.values())
    return sorted(todas, key=lambda a: (a.video, a.frame, a.anotador))


# =============================================================================
# Comparación con las paredes detectadas
# =============================================================================
def _errores(ref, det):
    ref = np.asarray(ref, float)
    det = np.asarray(det, float)
    ok = ~np.isnan(ref) & ~np.isnan(det)
    n = int(ok.sum())
    if n == 0:
        return {"n_columnas": 0, "sesgo_px": np.nan, "mae_px": np.nan, "rmse_px": np.nan, "max_abs_px": np.nan}
    e = det[ok] - ref[ok]
    return {"n_columnas": n, "sesgo_px": float(np.mean(e)), "mae_px": float(np.mean(np.abs(e))),
            "rmse_px": float(np.sqrt(np.mean(e ** 2))), "max_abs_px": float(np.max(np.abs(e)))}


def comparar_paredes(anotacion, sup_detectada, inf_detectada):
    """Errores de la detección respecto de la anotación (detectado − anotado), en px.

    Solo se usan las columnas donde ambas existen (ni NaN en la detección ni fuera del tramo
    anotado). sesgo > 0 = la detección queda más abajo (pared) o más ancha (diámetro)."""
    sup, inf = anotacion.paredes()
    sup_det = np.asarray(sup_detectada, float)
    inf_det = np.asarray(inf_detectada, float)
    if sup_det.shape != sup.shape or inf_det.shape != inf.shape:
        raise ValueError(f"las paredes detectadas deben tener largo {anotacion.ancho}")
    return {"superior": _errores(sup, sup_det), "inferior": _errores(inf, inf_det),
            "diametro": _errores(inf - sup, inf_det - sup_det)}


# =============================================================================
# Verificación
# =============================================================================
def verificar_anclas(anotacion, tol=1e-9):
    """La curva debe pasar exactamente por cada ancla (el cuadrito que se ve en la página).
    Devuelve el error máximo en px; lanza AssertionError si supera `tol`."""
    peor = 0.0
    for l in anotacion.lineas:
        err = np.abs(l.y(l.x_anclas) - l.y_anclas).max()
        peor = max(peor, float(err))
    if peor > tol:
        raise AssertionError(f"{anotacion.video} frame {anotacion.frame}: la curva se aparta {peor} px de un ancla")
    return peor


def imagen_verificacion(anotacion, frame_bgr, zoom=3):
    """El frame ampliado `zoom` veces (sin suavizar, como en la página) con las curvas y anclas
    dibujadas con la misma convención: la columna x ocupa [x*zoom, (x+1)*zoom) y su centro es
    (x + 0.5)*zoom."""
    import cv2
    colores = [(0, 255, 0), (80, 80, 255), (255, 170, 80), (0, 210, 255), (255, 0, 255), (255, 255, 0)]
    img = cv2.resize(frame_bgr, None, fx=zoom, fy=zoom, interpolation=cv2.INTER_NEAREST)
    S = 16
    for k, l in enumerate(anotacion.lineas):
        col = colores[k % len(colores)]
        xs = np.linspace(l.x_inicio, l.x_fin, max(2, int((l.x_fin - l.x_inicio) * zoom) + 1))
        ys = l.y(xs)
        pts = np.round(np.stack([(xs + 0.5) * zoom, (ys + 0.5) * zoom], 1) * S).astype(np.int32)
        cv2.polylines(img, [pts], False, col, 1, cv2.LINE_AA, shift=4)
        r = max(3, int(zoom * 1.2))
        for x, y in zip(l.x_anclas, l.y_anclas):
            cx, cy = int(round((x + 0.5) * zoom)), int(round((y + 0.5) * zoom))
            cv2.rectangle(img, (cx - r, cy - r), (cx + r, cy + r), col, 1)
        cv2.putText(img, f"L{k + 1}", (4, int(round((ys[0] + 0.5) * zoom)) - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 1, cv2.LINE_AA)
    if len(anotacion.lineas) == 2:
        r = anotacion.resumen()
        texto = f"{anotacion.video}  frame {anotacion.frame}  {anotacion.anotador}  diametro medio {r['diametro_medio_px']:.2f} px"
    else:
        texto = f"{anotacion.video}  frame {anotacion.frame}  {anotacion.anotador}  {len(anotacion.lineas)} linea(s)"
    img = cv2.copyMakeBorder(img, 0, 24, 0, 0, cv2.BORDER_CONSTANT, value=(20, 20, 20))
    cv2.putText(img, texto, (6, img.shape[0] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
    return img


def leer_frames(ruta_video, indices):
    """Frames pedidos, leyendo el video en orden (mismo índice que la web y arteria_braquial.py)."""
    import cv2
    pedidos, frames = set(indices), {}
    cap = cv2.VideoCapture(str(ruta_video))
    i, ultimo = 0, max(pedidos) if pedidos else -1
    while i <= ultimo:
        ok, f = cap.read()
        if not ok:
            break
        if i in pedidos:
            frames[i] = f
        i += 1
    cap.release()
    return frames


# =============================================================================
# Terminal
# =============================================================================
def escribir_csv(anotaciones, ruta):
    """Formato largo: una fila por (video, frame, anotador, columna x) dentro del tramo anotado."""
    filas = 0
    with open(ruta, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["video", "frame", "tiempo_s", "anotador", "x", "y_superior", "y_inferior", "diametro_px"])
        for a in anotaciones:
            try:
                sup, inf = a.paredes()
            except ValueError as exc:
                print(f"[aviso] {exc}; se omite.", file=sys.stderr)
                continue
            t = "" if a.tiempo_s is None else f"{a.tiempo_s:.4f}"
            for x in range(a.ancho):
                if math.isnan(sup[x]) and math.isnan(inf[x]):
                    continue
                d = inf[x] - sup[x]
                w.writerow([a.video, a.frame, t, a.anotador, x,
                            "" if math.isnan(sup[x]) else f"{sup[x]:.4f}",
                            "" if math.isnan(inf[x]) else f"{inf[x]:.4f}",
                            "" if math.isnan(d) else f"{d:.4f}"])
                filas += 1
    return filas


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("entradas", nargs="+", help="archivos .json exportados o carpetas que los contienen")
    ap.add_argument("--salida", default="paredes_anotadas.csv", help="CSV de salida (por defecto: paredes_anotadas.csv)")
    ap.add_argument("--imagenes", help="carpeta donde dibujar cada anotación sobre su frame para verificarla")
    ap.add_argument("--videos", default="../videos", help="carpeta con los .avi (para --imagenes)")
    ap.add_argument("--zoom", type=int, default=3, help="ampliación de las imágenes de verificación (por defecto: 3)")
    args = ap.parse_args()

    anotaciones = cargar_anotaciones(*args.entradas)
    if not anotaciones:
        sys.exit("No se encontraron anotaciones.")
    for a in anotaciones:
        verificar_anclas(a)
    print(f"{len(anotaciones)} anotaciones; todas las curvas pasan exactamente por sus anclas.")

    n = escribir_csv(anotaciones, args.salida)
    print(f"{args.salida}: {n} filas (una por columna anotada)")

    if args.imagenes:
        import cv2
        carpeta = Path(args.imagenes)
        carpeta.mkdir(parents=True, exist_ok=True)
        for vid in sorted({a.video for a in anotaciones}):
            delvideo = [a for a in anotaciones if a.video == vid]
            ruta = Path(args.videos) / f"{vid}.avi"
            if not ruta.exists():
                print(f"[aviso] no encontré {ruta}; sin imágenes para {vid}", file=sys.stderr)
                continue
            frames = leer_frames(ruta, [a.frame for a in delvideo])
            for a in delvideo:
                if a.frame in frames:
                    nombre = f"{vid}_f{a.frame:05d}_{''.join(c if c.isalnum() else '_' for c in a.anotador)}.png"
                    cv2.imwrite(str(carpeta / nombre), imagen_verificacion(a, frames[a.frame], args.zoom))
        print(f"Imágenes de verificación en {carpeta.resolve()}")


if __name__ == "__main__":
    main()

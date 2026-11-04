#!/usr/bin/env python3
"""
lineas_anotadas.py — Reconstruye numéricamente las anotaciones de las paredes de la arteria
a partir de los archivos que exporta la página web, para compararlas con las paredes detectadas.

Cada frame puede tener uno o los dos tipos de anotación:
  * 2 líneas curvables (pared superior e inferior), y/o
  * al menos 10 pares de puntos verticales: en una misma columna x, un punto en cada pared.
Las funciones que dan paredes o comparan aceptan fuente="lineas" o fuente="pares"; si no se
indica, se usan las líneas cuando el frame tiene 2, y si no, los pares.

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

    # Pares de puntos (si el frame los tiene):
    if a.pares_completos():
        x, y_sup, y_inf = a.puntos()                         # coordenadas exactas de cada par
        m_pares = comparar_paredes(a, sup_det, inf_det, fuente="pares")

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
MIN_PARES = 10          # mínimo de pares de puntos para que un frame cuente como completo


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
    pares: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))   # (n, 3): x, y_sup, y_inf
    fps: float = 0.0
    actualizado: str = ""
    archivo: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def tiempo_s(self):
        return self.frame / self.fps if self.fps else None

    @property
    def tipo(self):
        """"lineas", "pares" o "ambos": qué tiene anotado el frame."""
        if len(self.lineas) and len(self.pares):
            return "ambos"
        return "pares" if len(self.pares) else "lineas"

    def lineas_completas(self):
        return len(self.lineas) == 2

    def pares_completos(self, min_pares=MIN_PARES):
        return len(self.pares) >= min_pares

    def completa(self, min_pares=MIN_PARES):
        """Al menos uno de los dos tipos completo: 2 líneas, o `min_pares` pares de puntos o más."""
        return self.lineas_completas() or self.pares_completos(min_pares)

    def fuentes(self):
        """Tipos presentes, en orden: ["lineas"], ["pares"] o ["lineas", "pares"]."""
        return [f for f, n in (("lineas", len(self.lineas)), ("pares", len(self.pares))) if n]

    def _fuente(self, fuente):
        if fuente is None:
            fuente = "lineas" if self.lineas_completas() or not len(self.pares) else "pares"
        if fuente not in ("lineas", "pares"):
            raise ValueError('fuente debe ser "lineas" o "pares"')
        if fuente == "pares" and not len(self.pares):
            raise ValueError(f"{self.video} frame {self.frame} ({self.anotador}): no tiene pares de puntos")
        return fuente

    def puntos(self):
        """Pares de puntos: (x, y_superior, y_inferior), cada uno un arreglo de largo n (ordenados por x).
        Son exactamente las coordenadas marcadas en la página (x con decimales)."""
        return self.pares[:, 0].copy(), self.pares[:, 1].copy(), self.pares[:, 2].copy()

    def paredes(self, fuente=None):
        """(pared_superior, pared_inferior): arreglos de largo `ancho`, NaN donde no hay anotación.

        - Con líneas: el valor de la curva en cada columna del tramo anotado (requiere 2 líneas;
          la de arriba es la pared superior).
        - Con pares de puntos: solo en la columna más cercana a la x de cada par (si dos pares
          caen en la misma columna se promedian). Para comparar con la x exacta usa puntos()
          o comparar_paredes(), que interpola la detección en esa x.
        """
        if self._fuente(fuente) == "pares":
            sup = np.full(self.ancho, np.nan)
            inf = np.full(self.ancho, np.nan)
            cols = np.clip(np.rint(self.pares[:, 0]).astype(int), 0, self.ancho - 1)
            for c in np.unique(cols):
                m = cols == c
                sup[c] = self.pares[m, 1].mean()
                inf[c] = self.pares[m, 2].mean()
            return sup, inf
        if len(self.lineas) != 2:
            raise ValueError(f"{self.video} frame {self.frame} ({self.anotador}): tiene {len(self.lineas)} "
                             "línea(s); para las paredes se necesitan exactamente 2")
        return self.lineas[0].por_columna(self.ancho), self.lineas[1].por_columna(self.ancho)

    def diametro(self, fuente=None):
        """Distancia vertical por columna (pared inferior − superior); NaN donde no se solapan."""
        sup, inf = self.paredes(fuente)
        return inf - sup

    def resumen(self, fuente=None):
        if self._fuente(fuente) == "pares":
            x, s, i = self.puntos()
            d = i - s
            return {"n_columnas": len(d), "n_pares": len(d), "x_inicio": float(x.min()), "x_fin": float(x.max()),
                    "diametro_medio_px": float(np.mean(d)), "diametro_mediana_px": float(np.median(d)),
                    "diametro_min_px": float(np.min(d)), "diametro_max_px": float(np.max(d)),
                    "diametro_desv_px": float(np.std(d))}
        d = self.diametro("lineas")
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


def _pares_desde_json(pares):
    """[{x, y_superior, y_inferior}] -> arreglo (n, 3) ordenado por x, con y_sup < y_inf."""
    filas = []
    for q in pares or []:
        y1, y2 = float(q["y_superior"]), float(q["y_inferior"])
        filas.append((float(q["x"]), min(y1, y2), max(y1, y2)))
    return np.array(sorted(filas), float).reshape(-1, 3)


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
                pares = _pares_desde_json(a.get("pares"))
                if lineas or len(pares):
                    salida.append(Anotacion(video=vid, frame=int(f), anotador=anotador,
                                            ancho=int(v.get("ancho", 0)), alto=int(v.get("alto", 0)),
                                            fps=float(v.get("fps") or 0), lineas=lineas, pares=pares,
                                            actualizado=a.get("actualizado") or "", archivo=ruta.name))
    elif "mediciones" in datos and "frame" in datos:     # versión de escritorio con pares de puntos
        pares = _pares_desde_json({"x": m["punto_superior"]["x"], "y_superior": m["punto_superior"]["y"],
                                   "y_inferior": m["punto_inferior"]["y"]} for m in datos["mediciones"])
        if len(pares):
            salida.append(Anotacion(video=Path(datos.get("video", "")).stem, frame=int(datos["frame"]),
                                    anotador="escritorio", ancho=int(datos.get("ancho_px", 0)),
                                    alto=int(datos.get("alto_px", 0)), fps=float(datos.get("fps") or 0),
                                    lineas=[], pares=pares, actualizado=datos.get("exportado", ""),
                                    archivo=ruta.name))
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


def cargar_anotaciones(*entradas, ultima_version=True, solo_completas=True, min_pares=MIN_PARES):
    """Lee archivos .json y/o carpetas. Devuelve una lista de Anotacion ordenada por
    (video, frame, anotador). Si la misma persona anotó un frame en varios archivos, se queda con
    la versión editada más recientemente (ultima_version=True).

    Con solo_completas=True (por defecto) se descarta, con un aviso, lo incompleto de cada frame:
    los pares de puntos si son menos de `min_pares`, y las líneas si no son exactamente 2. Si a un
    frame no le queda nada, se omite."""
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
    if solo_completas:
        for a in todas:
            quien = f"{a.video} frame {a.frame} ({a.anotador})"
            if len(a.pares) and not a.pares_completos(min_pares):
                print(f"[aviso] {quien}: {len(a.pares)} pares de puntos (mínimo {min_pares}); se omiten los pares.",
                      file=sys.stderr)
                a.pares = np.zeros((0, 3))
            if len(a.lineas) and not a.lineas_completas():
                print(f"[aviso] {quien}: {len(a.lineas)} línea(s) (se necesitan 2); se omiten las líneas.",
                      file=sys.stderr)
                a.lineas = []
        todas = [a for a in todas if len(a.lineas) or len(a.pares)]
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


def interpolar_en(pared, x):
    """Valor de una pared por columna (arreglo con NaN) en posiciones x con decimales:
    interpolación lineal entre las dos columnas vecinas; NaN si alguna de ellas es NaN."""
    pared = np.asarray(pared, float)
    x = np.asarray(x, float)
    x0 = np.clip(np.floor(x).astype(int), 0, len(pared) - 1)
    x1 = np.clip(x0 + 1, 0, len(pared) - 1)
    t = x - x0
    v = (1 - t) * pared[x0] + t * pared[x1]
    return np.where(t == 0, pared[x0], v)


def comparar_paredes(anotacion, sup_detectada, inf_detectada, fuente=None):
    """Errores de la detección respecto de la anotación (detectado − anotado), en px.

    - Líneas: se usan las columnas donde ambas existen (ni NaN en la detección ni fuera del tramo
      anotado).
    - Pares de puntos: la detección se evalúa en la x exacta de cada par (interpolando entre
      columnas vecinas); los pares donde la detección es NaN no cuentan.
    fuente: "lineas" o "pares" (por defecto, las líneas si el frame tiene 2; si no, los pares).
    sesgo > 0 = la detección queda más abajo (pared) o más ancha (diámetro)."""
    sup_det = np.asarray(sup_detectada, float)
    inf_det = np.asarray(inf_detectada, float)
    if sup_det.shape != (anotacion.ancho,) or inf_det.shape != (anotacion.ancho,):
        raise ValueError(f"las paredes detectadas deben tener largo {anotacion.ancho}")
    fuente = anotacion._fuente(fuente)
    if fuente == "pares":
        x, sup, inf = anotacion.puntos()
        sd, idt = interpolar_en(sup_det, x), interpolar_en(inf_det, x)
        return {"superior": _errores(sup, sd), "inferior": _errores(inf, idt),
                "diametro": _errores(inf - sup, idt - sd)}
    sup, inf = anotacion.paredes("lineas")
    return {"superior": _errores(sup, sup_det), "inferior": _errores(inf, inf_det),
            "diametro": _errores(inf - sup, inf_det - sup_det)}


# =============================================================================
# Verificación
# =============================================================================
def verificar_anclas(anotacion, tol=1e-9):
    """La curva debe pasar exactamente por cada ancla (el cuadrito que se ve en la página).
    Devuelve el error máximo en px; lanza AssertionError si supera `tol`."""
    if len(anotacion.pares):
        assert np.all(anotacion.pares[:, 1] < anotacion.pares[:, 2]), "par con y_superior >= y_inferior"
    peor = 0.0
    for l in anotacion.lineas:
        err = np.abs(l.y(l.x_anclas) - l.y_anclas).max()
        peor = max(peor, float(err))
    if peor > tol:
        raise AssertionError(f"{anotacion.video} frame {anotacion.frame}: la curva se aparta {peor} px de un ancla")
    return peor


def imagen_verificacion(anotacion, frame_bgr, zoom=3, fuente=None):
    """El frame ampliado `zoom` veces (sin suavizar, como en la página) con las curvas y anclas
    dibujadas con la misma convención: la columna x ocupa [x*zoom, (x+1)*zoom) y su centro es
    (x + 0.5)*zoom. Como en la página, se dibuja un solo tipo: fuente="lineas" o "pares"."""
    fuente = anotacion._fuente(fuente)
    import cv2
    colores = [(0, 255, 0), (80, 80, 255), (255, 170, 80), (0, 210, 255), (255, 0, 255), (255, 255, 0)]
    img = cv2.resize(frame_bgr, None, fx=zoom, fy=zoom, interpolation=cv2.INTER_NEAREST)
    S = 16
    for k, l in enumerate(anotacion.lineas if fuente == "lineas" else []):
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
    for x, ys, yi in (anotacion.pares if fuente == "pares" else []):
        cx = int(round((x + 0.5) * zoom))
        p1, p2 = int(round((ys + 0.5) * zoom)), int(round((yi + 0.5) * zoom))
        r = max(3, int(zoom * 1.1))
        cv2.line(img, (cx, p1), (cx, p2), (255, 229, 0), 1, cv2.LINE_AA)
        for py in (p1, p2):
            cv2.circle(img, (cx, py), r, (255, 229, 0), 1, cv2.LINE_AA)
            cv2.line(img, (cx - 2 * r, py), (cx + 2 * r, py), (255, 229, 0), 1)
    if fuente == "pares":
        r = anotacion.resumen("pares")
        texto = (f"{anotacion.video}  frame {anotacion.frame}  {anotacion.anotador}  {r['n_pares']} pares  "
                 f"diametro medio {r['diametro_medio_px']:.2f} px")
    elif len(anotacion.lineas) == 2:
        r = anotacion.resumen("lineas")
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
    """Formato largo: una fila por punto anotado.
    - tipo "lineas": una fila por columna entera x dentro del tramo anotado.
    - tipo "pares":  una fila por par de puntos, con su x exacta."""
    filas = 0
    with open(ruta, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["video", "frame", "tiempo_s", "anotador", "tipo", "x", "y_superior", "y_inferior", "diametro_px"])
        for a in anotaciones:
            t = "" if a.tiempo_s is None else f"{a.tiempo_s:.4f}"
            for x, ys, yi in a.pares:
                w.writerow([a.video, a.frame, t, a.anotador, "pares", f"{x:.4f}", f"{ys:.4f}", f"{yi:.4f}", f"{yi - ys:.4f}"])
                filas += 1
            if not len(a.lineas):
                continue
            try:
                sup, inf = a.paredes("lineas")
            except ValueError as exc:
                print(f"[aviso] {exc}; se omiten las líneas.", file=sys.stderr)
                continue
            for x in range(a.ancho):
                if math.isnan(sup[x]) and math.isnan(inf[x]):
                    continue
                d = inf[x] - sup[x]
                w.writerow([a.video, a.frame, t, a.anotador, "lineas", x,
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
    ap.add_argument("--min-pares", type=int, default=MIN_PARES, help=f"mínimo de pares por frame (por defecto: {MIN_PARES})")
    ap.add_argument("--incluir-incompletas", action="store_true", help="no descartar frames incompletos")
    args = ap.parse_args()

    anotaciones = cargar_anotaciones(*args.entradas, solo_completas=not args.incluir_incompletas,
                                     min_pares=args.min_pares)
    if not anotaciones:
        sys.exit("No se encontraron anotaciones.")
    for a in anotaciones:
        verificar_anclas(a)
    nl = sum(bool(len(a.lineas)) for a in anotaciones)
    np_ = sum(bool(len(a.pares)) for a in anotaciones)
    print(f"{len(anotaciones)} frames anotados ({nl} con líneas, {np_} con pares de puntos); "
          "todas las curvas pasan exactamente por sus anclas.")

    n = escribir_csv(anotaciones, args.salida)
    print(f"{args.salida}: {n} filas (una por columna anotada o por par de puntos)")

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
                    base = f"{vid}_f{a.frame:05d}_{''.join(c if c.isalnum() else '_' for c in a.anotador)}"
                    for fuente in a.fuentes():
                        cv2.imwrite(str(carpeta / f"{base}_{fuente}.png"),
                                    imagen_verificacion(a, frames[a.frame], args.zoom, fuente))
        print(f"Imágenes de verificación en {carpeta.resolve()}")


if __name__ == "__main__":
    main()

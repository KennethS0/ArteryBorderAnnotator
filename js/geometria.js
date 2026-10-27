// geometria.js — Geometría de las líneas curvables.
//
// Es una traducción exacta de las funciones de ground_truth/anotador_frames_v2.py, para que
// la web y la herramienta de escritorio dibujen y midan exactamente lo mismo.
//
// Modelo:  linea = { altura: Number, anclas: [{x, dy}, ...] }  (anclas ordenadas por x)
//          y_ancla = altura + dy
// La curva pasa por las anclas y se interpola con PCHIP (Hermite cúbico monótono,
// igual a scipy.interpolate.PchipInterpolator).

const sign = (v) => (v > 0 ? 1 : v < 0 ? -1 : 0);

function pendienteExtremo(h0, h1, m0, m1) {
  const d = ((2 * h0 + h1) * m0 - h0 * m1) / (h0 + h1);
  if (sign(d) !== sign(m0)) return 0;
  if (sign(m0) !== sign(m1) && Math.abs(d) > Math.abs(3 * m0)) return 3 * m0;
  return d;
}

/** Interpolación PCHIP (Fritsch–Carlson). Fuera de [xk0, xkN] mantiene el valor del extremo. */
export function pchip(xk, yk, xq) {
  const n = xk.length;
  const out = new Float64Array(xq.length);
  if (n === 1) { out.fill(yk[0]); return out; }
  const h = new Float64Array(n - 1), m = new Float64Array(n - 1);
  for (let i = 0; i < n - 1; i++) { h[i] = xk[i + 1] - xk[i]; m[i] = (yk[i + 1] - yk[i]) / h[i]; }
  const d = new Float64Array(n);
  if (n === 2) { d[0] = d[1] = m[0]; } else {
    for (let k = 1; k < n - 1; k++) {
      if (m[k - 1] * m[k] > 0) {
        const w1 = 2 * h[k] + h[k - 1], w2 = h[k] + 2 * h[k - 1];
        d[k] = (w1 + w2) / (w1 / m[k - 1] + w2 / m[k]);
      } else d[k] = 0;
    }
    d[0] = pendienteExtremo(h[0], h[1], m[0], m[1]);
    d[n - 1] = pendienteExtremo(h[n - 2], h[n - 3], m[n - 2], m[n - 3]);
  }
  for (let q = 0; q < xq.length; q++) {
    const x = Math.min(Math.max(xq[q], xk[0]), xk[n - 1]);
    // búsqueda binaria del intervalo (equivale a searchsorted(side="right") - 1)
    let lo = 0, hi = n - 1;
    while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (xk[mid] <= x) lo = mid; else hi = mid; }
    const i = Math.min(lo, n - 2);
    if (n === 2) { out[q] = yk[0] + m[0] * (x - xk[0]); continue; }
    const t = (x - xk[i]) / h[i], t2 = t * t, t3 = t2 * t;
    out[q] = (2 * t3 - 3 * t2 + 1) * yk[i] + (t3 - 2 * t2 + t) * h[i] * d[i]
      + (-2 * t3 + 3 * t2) * yk[i + 1] + (t3 - t2) * h[i] * d[i + 1];
  }
  return out;
}

export function lineaY(linea, xs) {
  const xk = linea.anclas.map((a) => a.x);
  const yk = linea.anclas.map((a) => linea.altura + a.dy);
  return pchip(xk, yk, xs);
}

export const lineaRango = (l) => [l.anclas[0].x, l.anclas[l.anclas.length - 1].x];

export function linspace(a, b, n) {
  if (n === 1) return [a];
  const out = new Array(n);
  for (let i = 0; i < n; i++) out[i] = a + ((b - a) * i) / (n - 1);
  return out;
}

export function lineaYMedia(l) {
  const [x0, x1] = lineaRango(l);
  const ys = lineaY(l, linspace(x0, x1, 64));
  let s = 0; for (const v of ys) s += v;
  return s / ys.length;
}

/** Índices de las líneas ordenados de arriba hacia abajo. */
export function ordenVertical(lineas) {
  const medias = lineas.map(lineaYMedia);
  return lineas.map((_, i) => i).sort((a, b) => medias[a] - medias[b]);
}

/** Distancia vertical por columna entera en el tramo común: {cols, d} o null. */
export function distanciasEntre(arriba, abajo) {
  const x0 = Math.max(lineaRango(arriba)[0], lineaRango(abajo)[0]);
  const x1 = Math.min(lineaRango(arriba)[1], lineaRango(abajo)[1]);
  const c0 = Math.ceil(x0), c1 = Math.floor(x1);
  if (c1 < c0) return null;
  const cols = []; for (let c = c0; c <= c1; c++) cols.push(c);
  const ya = lineaY(arriba, cols), yb = lineaY(abajo, cols);
  return { cols, d: cols.map((_, i) => yb[i] - ya[i]) };
}

/** [{a, b, cols, d}] para cada par de líneas vecinas (de arriba hacia abajo). */
export function distanciasConsecutivas(lineas) {
  const orden = ordenVertical(lineas);
  const pares = [];
  for (let k = 0; k + 1 < orden.length; k++) {
    const r = distanciasEntre(lineas[orden[k]], lineas[orden[k + 1]]);
    if (r) pares.push({ a: orden[k], b: orden[k + 1], ...r });
  }
  return pares;
}

export const media = (v) => v.reduce((s, x) => s + x, 0) / v.length;
export const r1 = (v) => Math.round(v * 10) / 10;

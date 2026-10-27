// app.js — Interfaz del anotador (equivalente web de ground_truth/anotador_frames_v2.py).
//
// Recibe un `backend` con la lista de videos, las URLs de los bloques de frames y la
// lectura/escritura/exportación de anotaciones (ver almacen-local.js).

import * as G from "./geometria.js";
import { META_FRAMES_POR_VIDEO, AUTOGUARDADO_S } from "./config.js";

const COLORES = ["#00ff00", "#ff5050", "#50aaff", "#ffd200", "#ff00ff", "#00ffff"];
const RADIO_CLIC = 10;         // px de pantalla para "atrapar" un ancla o una línea
const ZOOM_PASO = 1.25;
const ZOOM_MAX = 40;           // px de pantalla por px de imagen
const ANCLAS_INICIALES = 5;
const SEP_MIN_ANCLAS = 0.5;    // px de imagen entre anclas vecinas
const TRAMO_MIN_PANTALLA = 6;  // arrastre más corto = clic simple (línea de borde a borde)
const MAX_HISTORIAL = 100;
const BLOQUES_EN_MEMORIA = 12;

const $ = (id) => document.getElementById(id);
const clamp = (v, a, b) => Math.min(Math.max(v, a), b);
const r1 = G.r1;
const copiar = (o) => JSON.parse(JSON.stringify(o));

export function iniciarApp(backend) {
  // ------------------------------------------------------------------ estado
  const st = {
    usuario: null,
    videos: [],
    video: null,
    frame: 0,
    lineas: new Map(),        // frame -> [{altura, anclas:[{x, dy}]}]
    sinGuardar: new Set(),
    guardando: new Set(),
    errorGuardado: null,
    timers: new Map(),
    historial: new Map(),     // frame -> [copias]
    bloques: new Map(),       // nº bloque -> Promise<HTMLImageElement> (LRU)
    imgBloque: null,          // {b, img} del frame actual
    cargando: false,
    modo: null,               // null (edición) | "nueva" | "eliminar"
    sel: null,
    drag: null,
    pan: null,
    escala: 1,
    off: [0, 0],
    ajustado: true,
    cursor: null,
    cursorTipo: "crosshair",
  };

  const lienzo = $("lienzo");
  const ctx = lienzo.getContext("2d");
  const cont = $("lienzo-contenedor");

  // ------------------------------------------------------------------ inicio
  (async () => {
    requestAnimationFrame(redimensionar);
    try {
      st.videos = await backend.listarVideos();
    } catch (e) {
      return estado(`No se pudo leer la lista de videos: ${e.message || e}`);
    }
    const sel = $("sel-video");
    sel.innerHTML = "";
    for (const v of st.videos) sel.add(new Option(v.nombre || v.id, v.id));
    if (!st.videos.length) return estado("Todavía no hay videos. Genera los frames con scripts/preparar_frames.py.");
    const h = leerHash();
    const v = st.videos.find((x) => x.id === h.video) || st.videos[0];
    sel.value = v.id;
    await abrirVideo(v, h.video === v.id ? h.frame : null);
  })();

  // ------------------------------------------------- descargar / cargar archivo
  const dlg = $("dlg-descargar");
  function abrirDescarga() {
    guardarTodo();
    const { frames, videos } = backend.resumen();
    $("dlg-resumen").textContent = frames
      ? `Se descargarán ${frames} frame${frames === 1 ? "" : "s"} anotado${frames === 1 ? "" : "s"} `
        + `en ${videos} video${videos === 1 ? "" : "s"}.`
      : "Todavía no has anotado ningún frame.";
    $("dlg-nombre").value = backend.nombre;
    $("dlg-ok").disabled = !frames;
    dlg.showModal();
    $("dlg-nombre").focus();
  }
  $("btn-descargar").onclick = abrirDescarga;
  $("dlg-cancelar").onclick = () => dlg.close();
  $("dlg-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const nombre = $("dlg-nombre").value.trim();
    if (!nombre) { $("dlg-nombre").focus(); return; }
    backend.nombre = nombre;
    const datos = backend.exportar(nombre);
    const slug = nombre.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^A-Za-z0-9]+/g, "_")
      .replace(/^_|_$/g, "").toLowerCase() || "anotador";
    const fecha = new Date().toISOString().slice(0, 16).replace("T", "_").replace(":", "-");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([JSON.stringify(datos, null, 1)], { type: "application/json" }));
    a.download = `anotaciones_${slug}_${fecha}.json`;
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 10000);
    backend.marcarDescargado();
    dlg.close();
    actualizarIndicador();
    estado(`Descargado ${a.download}. Envíalo al equipo del proyecto.`);
  });

  $("btn-cargar").onclick = () => $("in-archivo").click();
  $("in-archivo").addEventListener("change", async (e) => {
    const archivo = e.target.files[0];
    e.target.value = "";
    if (!archivo) return;
    try {
      await guardarTodo();
      const n = backend.importar(JSON.parse(await archivo.text()));
      if (st.video) await abrirVideo(st.video, st.frame);
      estado(`Cargados ${n} frames de ${archivo.name}.`);
    } catch (err) {
      estado(`No se pudo cargar ${archivo.name}: ${err.message || err}`);
    }
  });

  function leerHash() {
    const p = new URLSearchParams(location.hash.slice(1));
    const f = parseInt(p.get("f"), 10);
    return { video: p.get("v"), frame: Number.isFinite(f) ? f : null };
  }

  // Si se edita o pega un enlace #v=<video>&f=<frame> con la página abierta, se navega ahí.
  window.addEventListener("hashchange", async () => {
    if (!st.video) return;
    const h = leerHash();
    const v = st.videos.find((x) => x.id === h.video);
    if (v && v !== st.video) {
      $("sel-video").value = v.id;
      await abrirVideo(v, h.frame);
    } else if (h.frame !== null) {
      irA(clamp(h.frame, 0, st.video.n_frames - 1));
    }
  });

  // ------------------------------------------------------------------ videos
  $("sel-video").onchange = async (e) => {
    const v = st.videos.find((x) => x.id === e.target.value);
    if (v && v !== st.video) await abrirVideo(v, null);
  };

  async function abrirVideo(video, frame) {
    await guardarTodo();
    st.video = video;
    st.bloques.clear();
    st.imgBloque = null;
    st.historial.clear();
    st.sinGuardar.clear();
    st.lineas = new Map();
    $("lbl-total").textContent = `/ ${video.n_frames - 1}`;
    estado("Cargando anotaciones…");
    try {
      const mias = await backend.misAnotaciones(video);
      for (const [f, a] of mias) {
        st.lineas.set(f, a.lineas.map((l) => ({
          altura: l.altura,
          anclas: l.anclas.map((x) => ({ x: x.x, dy: x.dy })).sort((p, q) => p.x - q.x),
        })));
      }
    } catch (e) {
      estado(`No se pudieron leer tus anotaciones: ${e.message || e}`);
    }
    renderLista();
    const inicial = frame ?? 0;
    await irA(clamp(inicial, 0, video.n_frames - 1), true);
  }

  // ---------------------------------------------------------- frames/bloques
  function bloqueDe(f) { return Math.floor(f / st.video.bloque); }

  function cargarBloque(b) {
    const video = st.video;
    if (st.bloques.has(b)) {
      const p = st.bloques.get(b);
      st.bloques.delete(b); st.bloques.set(b, p);          // LRU: al final = más reciente
      return p;
    }
    const p = (async () => {
      const url = await backend.urlBloque(video, b);
      const img = new Image();
      img.decoding = "async";
      img.src = url;
      await img.decode();
      return img;
    })();
    p.catch(() => st.bloques.delete(b));
    st.bloques.set(b, p);
    while (st.bloques.size > BLOQUES_EN_MEMORIA) st.bloques.delete(st.bloques.keys().next().value);
    return p;
  }

  async function irA(f, forzar = false) {
    const v = st.video;
    if (!v || f < 0 || f >= v.n_frames || (f === st.frame && !forzar && st.imgBloque)) return;
    if (f !== st.frame && st.sinGuardar.has(st.frame)) guardarFrame(st.frame);
    st.frame = f;
    st.sel = null;
    st.drag = null;
    $("in-frame").value = f;
    $("btn-ant").disabled = f === 0;
    $("btn-sig").disabled = f >= v.n_frames - 1;
    history.replaceState(null, "", `#v=${encodeURIComponent(v.id)}&f=${f}`);
    actualizarAlturaUI();
    renderLista();

    const b = bloqueDe(f);
    if (!st.imgBloque || st.imgBloque.b !== b) {
      st.cargando = true;
      $("cargando").hidden = false;
      estado();
      try {
        const img = await cargarBloque(b);
        if (st.video !== v || bloqueDe(st.frame) !== b) return;   // el usuario ya se movió
        st.imgBloque = { b, img };
      } catch (e) {
        if (st.video === v && st.frame === f) estado(`No se pudo cargar el frame ${f}: ${e.message || e}`);
        return;
      } finally {
        if (st.video === v && bloqueDe(st.frame) === b) { st.cargando = false; $("cargando").hidden = true; }
      }
    }
    // Precarga el bloque vecino si estamos cerca del borde del actual.
    const pos = f % v.bloque, nb = Math.ceil(v.n_frames / v.bloque);
    if (pos >= v.bloque - 3 && b + 1 < nb) cargarBloque(b + 1).catch(() => {});
    if (pos <= 2 && b > 0) cargarBloque(b - 1).catch(() => {});
    estado();
    dibujar();
  }

  $("btn-ant").onclick = () => irA(st.frame - 1);
  $("btn-sig").onclick = () => irA(st.frame + 1);
  $("in-frame").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      const n = parseInt(e.target.value, 10);
      if (!Number.isFinite(n)) { e.target.value = st.frame; return estado("Número de frame no válido."); }
      irA(clamp(n, 0, st.video.n_frames - 1));
      lienzo.focus();
    } else if (e.key === "Escape") { e.target.value = st.frame; lienzo.focus(); }
  });

  // ---------------------------------------------------------------- guardado
  function lineasFrame(f = st.frame) {
    if (!st.lineas.has(f)) st.lineas.set(f, []);
    return st.lineas.get(f);
  }

  function marcarCambio(msg) {
    st.sinGuardar.add(st.frame);
    programarGuardado(st.frame);
    if (!selValida()) st.sel = null;
    actualizarAlturaUI(true);
    estado(msg);
    renderLista();
    dibujar();
  }

  function programarGuardado(f, segundos = AUTOGUARDADO_S) {
    clearTimeout(st.timers.get(f));
    st.timers.set(f, setTimeout(() => guardarFrame(f), segundos * 1000));
    actualizarIndicador();
  }

  async function guardarFrame(f) {
    clearTimeout(st.timers.get(f));
    st.timers.delete(f);
    if (!st.sinGuardar.has(f)) return;
    const video = st.video;
    const actuales = st.lineas.get(f) || [];
    // Se guardan de arriba hacia abajo, igual que en el JSON de la herramienta de escritorio.
    const lineas = G.ordenVertical(actuales).map((i) => ({
      altura: r1(actuales[i].altura),
      anclas: actuales[i].anclas.map((a) => ({ x: r1(a.x), dy: r1(a.dy) })),
    }));
    st.sinGuardar.delete(f);
    st.guardando.add(f);
    actualizarIndicador();
    try {
      await backend.guardar(video, f, lineas);
      st.errorGuardado = null;
    } catch (e) {
      st.errorGuardado = e.message || String(e);
      if (st.video === video) { st.sinGuardar.add(f); programarGuardado(f, 5); }
    } finally {
      st.guardando.delete(f);
      actualizarIndicador();
      renderLista();
    }
  }

  async function guardarTodo() {
    await Promise.all([...st.sinGuardar].map(guardarFrame));
  }

  // El respaldo en el navegador es inmediato; lo que importa es si falta descargar el archivo.
  function actualizarIndicador() {
    const el = $("lbl-guardado");
    const btn = $("btn-descargar");
    if (st.errorGuardado && st.sinGuardar.size) {
      el.textContent = "No se pudo guardar en el navegador · descarga tus anotaciones";
      el.dataset.estado = "error";
      el.title = st.errorGuardado;
    } else if (backend.pendienteDescarga() || st.sinGuardar.size) {
      el.textContent = "Cambios sin descargar";
      el.dataset.estado = "pendiente";
      el.title = "Tus anotaciones están guardadas en este navegador. Al terminar, descárgalas y envía el archivo.";
    } else {
      const { frames } = backend.resumen();
      el.textContent = frames ? "Todo descargado" : "Sin anotaciones";
      el.dataset.estado = "ok";
      el.title = "";
    }
    btn.classList.toggle("pendiente", el.dataset.estado !== "ok");
  }

  // Al cerrar o recargar, lo pendiente se escribe en el navegador (es instantáneo).
  window.addEventListener("pagehide", () => { guardarTodo(); });

  // ------------------------------------------------------- panel de frames
  function renderLista() {
    const ul = $("lista-frames");
    ul.innerHTML = "";
    const frames = [...st.lineas.entries()].filter(([, l]) => l.length).map(([f]) => f).sort((a, b) => a - b);
    $("lbl-progreso").textContent = `${frames.length} / ${META_FRAMES_POR_VIDEO}`;
    $("barra-progreso").style.width = `${Math.min(100, (100 * frames.length) / META_FRAMES_POR_VIDEO)}%`;
    if (!frames.length) {
      const li = document.createElement("li");
      li.className = "vacio";
      li.textContent = "Aún no has anotado frames en este video.";
      ul.append(li);
      return;
    }
    for (const f of frames) {
      const ls = st.lineas.get(f);
      const pares = G.distanciasConsecutivas(ls);
      const li = document.createElement("li");
      if (f === st.frame) li.className = "actual";
      const btn = document.createElement("button");
      btn.type = "button";
      btn.onclick = () => { irA(f); lienzo.focus(); };
      const n = document.createElement("span");
      n.className = "num";
      n.textContent = `Frame ${f}`;
      const d = document.createElement("span");
      d.className = "dato";
      d.textContent = pares.length === 1 ? `${G.media(pares[0].d).toFixed(1)} px`
        : `${ls.length} línea${ls.length === 1 ? "" : "s"}`;
      btn.append(n, d);
      if (st.sinGuardar.has(f) || st.guardando.has(f)) {
        const p = document.createElement("span");
        p.className = "pendiente";
        p.title = "Sin guardar";
        btn.append(p);
      }
      li.append(btn);
      ul.append(li);
    }
  }

  // ------------------------------------------------------------- coordenadas
  const tam = () => [cont.clientWidth, cont.clientHeight];
  const imgACanvas = (x, y) => [(x + 0.5) * st.escala + st.off[0], (y + 0.5) * st.escala + st.off[1]];
  const canvasAImgLibre = (cx, cy) => [(cx - st.off[0]) / st.escala - 0.5, (cy - st.off[1]) / st.escala - 0.5];
  function canvasAImg(cx, cy) {
    if (!st.video) return null;
    const [x, y] = canvasAImgLibre(cx, cy);
    if (x < -0.5 || x > st.video.ancho - 0.5 || y < -0.5 || y > st.video.alto - 0.5) return null;
    return [r1(x), r1(y)];
  }
  function posEvento(e) {
    const r = lienzo.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top];
  }

  // -------------------------------------------------------------------- zoom
  const escalaAjuste = () => { const [cw, ch] = tam(); return Math.min(cw / st.video.ancho, ch / st.video.alto); };

  function ajustarVista() { st.ajustado = true; dibujar(); }

  function zoomEn(factor, cx, cy) {
    if (!st.video) return;
    const [cw, ch] = tam();
    if (cx === undefined) { cx = cw / 2; cy = ch / 2; }
    const sFit = escalaAjuste();
    const sNueva = Math.min(Math.max(ZOOM_MAX, sFit), Math.max(sFit, st.escala * factor));
    if (sNueva <= sFit * 1.001) return ajustarVista();
    const px = (cx - st.off[0]) / st.escala, py = (cy - st.off[1]) / st.escala;
    st.ajustado = false;
    st.escala = sNueva;
    st.off = [cx - px * sNueva, cy - py * sNueva];
    dibujar();
  }

  function limitarVista() {
    const [cw, ch] = tam();
    const nw = st.video.ancho * st.escala, nh = st.video.alto * st.escala;
    let [ox, oy] = st.off;
    ox = nw <= cw ? (cw - nw) / 2 : Math.min(0, Math.max(cw - nw, ox));
    oy = nh <= ch ? (ch - nh) / 2 : Math.min(0, Math.max(ch - nh, oy));
    st.off = [ox, oy];
  }

  $("btn-zoom-menos").onclick = () => zoomEn(1 / ZOOM_PASO);
  $("btn-zoom-mas").onclick = () => zoomEn(ZOOM_PASO);
  $("btn-ajustar").onclick = ajustarVista;
  lienzo.addEventListener("wheel", (e) => {
    e.preventDefault();
    const [cx, cy] = posEvento(e);
    zoomEn(e.deltaY < 0 ? ZOOM_PASO : 1 / ZOOM_PASO, cx, cy);
  }, { passive: false });

  // ------------------------------------------------------------------ líneas
  const selValida = () => st.sel !== null && st.sel >= 0 && st.sel < (st.lineas.get(st.frame) || []).length;

  function limitarAltura(linea, altura) {
    const dys = linea.anclas.map((a) => a.dy);
    return clamp(altura, -Math.min(...dys), st.video.alto - 1 - Math.max(...dys));
  }

  function buscarAncla(cx, cy) {
    let mejor = null, dmin = RADIO_CLIC;
    (st.lineas.get(st.frame) || []).forEach((l, i) => l.anclas.forEach((a, j) => {
      const [ax, ay] = imgACanvas(a.x, l.altura + a.dy);
      const d = Math.hypot(ax - cx, ay - cy);
      if (d <= dmin) { mejor = [i, j]; dmin = d; }
    }));
    return mejor;
  }

  function buscarLinea(cx, cy) {
    const [x] = canvasAImgLibre(cx, cy);
    const tol = RADIO_CLIC / st.escala;
    let mejor = null, dmin = RADIO_CLIC;
    (st.lineas.get(st.frame) || []).forEach((l, i) => {
      const [x0, x1] = G.lineaRango(l);
      if (x < x0 - tol || x > x1 + tol) return;
      const [, ly] = imgACanvas(0, G.lineaY(l, [x])[0]);
      const d = Math.abs(ly - cy);
      if (d <= dmin) { mejor = i; dmin = d; }
    });
    return mejor;
  }

  function guardarHistorial() {
    if (!st.historial.has(st.frame)) st.historial.set(st.frame, []);
    const pila = st.historial.get(st.frame);
    pila.push(copiar(lineasFrame()));
    if (pila.length > MAX_HISTORIAL) pila.shift();
  }
  const descartarHistorial = () => st.historial.get(st.frame)?.pop();

  function deshacer() {
    const pila = st.historial.get(st.frame);
    if (!pila?.length) return estado("No hay nada que deshacer en este frame.");
    st.lineas.set(st.frame, pila.pop());
    st.sel = null;
    marcarCambio("Cambio deshecho.");
  }

  function eliminarSeleccionada() {
    if (!selValida()) return;
    guardarHistorial();
    lineasFrame().splice(st.sel, 1);
    st.sel = null;
    marcarCambio("Línea eliminada.");
  }

  function moverAltura(delta) {
    if (!selValida()) return;
    const l = lineasFrame()[st.sel];
    guardarHistorial();
    l.altura = r1(limitarAltura(l, l.altura + delta));
    marcarCambio();
  }

  function ordenarLineas(seguir) {
    const ls = lineasFrame();
    const obj = seguir !== null && seguir !== undefined ? ls[seguir] : null;
    const orden = G.ordenVertical(ls);
    const nuevas = orden.map((i) => ls[i]);
    ls.splice(0, ls.length, ...nuevas);
    const i = ls.indexOf(obj);
    return i >= 0 ? i : null;
  }

  // --------------------------------------------------------------- altura UI
  const inAltura = $("in-altura");
  function actualizarAlturaUI(forzar = false) {
    if (selValida()) {
      inAltura.disabled = false;
      if (forzar || document.activeElement !== inAltura) inAltura.value = lineasFrame()[st.sel].altura.toFixed(1);
    } else {
      inAltura.value = "";
      inAltura.disabled = true;
    }
  }
  inAltura.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      if (!selValida()) return;
      const v = parseFloat(inAltura.value.replace(",", "."));
      if (!Number.isFinite(v)) { estado(`"${inAltura.value}" no es una altura válida.`); return actualizarAlturaUI(true); }
      const l = lineasFrame()[st.sel];
      guardarHistorial();
      l.altura = r1(limitarAltura(l, v));
      lienzo.focus();
      marcarCambio();
    } else if (e.key === "Escape") { actualizarAlturaUI(true); lienzo.focus(); }
  });
  inAltura.addEventListener("blur", () => actualizarAlturaUI(true));

  // ------------------------------------------------------------------- modos
  function cambiarModo(modo, forzar = false) {
    if (forzar || st.modo === modo) modo = null;
    st.modo = modo;
    st.drag = null;
    $("btn-nueva").classList.toggle("activo", modo === "nueva");
    $("btn-eliminar").classList.toggle("activo", modo === "eliminar");
    $("btn-nueva").setAttribute("aria-pressed", modo === "nueva");
    $("btn-eliminar").setAttribute("aria-pressed", modo === "eliminar");
    setCursor("crosshair");
    estado();
    dibujar();
  }
  $("btn-nueva").onclick = () => { cambiarModo("nueva"); lienzo.focus(); };
  $("btn-eliminar").onclick = () => { cambiarModo("eliminar"); lienzo.focus(); };

  function setCursor(t) {
    if (t !== st.cursorTipo) { st.cursorTipo = t; lienzo.style.cursor = t; }
  }

  // ------------------------------------------------------------- interacción
  lienzo.addEventListener("contextmenu", (e) => e.preventDefault());

  lienzo.addEventListener("pointerdown", (e) => {
    if (!st.video || !st.imgBloque) return;
    lienzo.focus();
    const [cx, cy] = posEvento(e);
    if (e.button === 1 || e.button === 2) {                     // mover la vista
      e.preventDefault();
      if (st.ajustado) return;
      st.pan = { x: cx, y: cy, off: [...st.off] };
      lienzo.setPointerCapture(e.pointerId);
      return setCursor("grabbing");
    }
    if (e.button !== 0) return;
    lienzo.setPointerCapture(e.pointerId);
    // Doble clic: segundo clic rápido en el mismo lugar.
    const ahora = performance.now(), ult = st.ultimoClic;
    st.ultimoClic = { t: ahora, x: cx, y: cy, modo: st.modo };
    if (ult && ahora - ult.t < 350 && Math.hypot(cx - ult.x, cy - ult.y) < 5) {
      st.ultimoClic = null;
      if (ult.modo === null && st.modo === null) return dobleClic(cx, cy);   // agrega un ancla
      if (st.modo !== null) return;    // en Nueva/Eliminar, un doble clic cuenta como un solo clic
    }
    presionar(cx, cy);
  });

  lienzo.addEventListener("pointermove", (e) => {
    const [cx, cy] = posEvento(e);
    if (st.pan) {
      st.off = [st.pan.off[0] + cx - st.pan.x, st.pan.off[1] + cy - st.pan.y];
      return dibujar();
    }
    if (st.drag) return arrastrar(cx, cy);
    st.cursor = canvasAImg(cx, cy);
    if (st.modo === null && st.video) {
      if (buscarAncla(cx, cy)) setCursor("move");
      else if (buscarLinea(cx, cy) !== null) setCursor("ns-resize");
      else setCursor("crosshair");
    }
    estado();
  });

  lienzo.addEventListener("pointerup", (e) => {
    const [cx] = posEvento(e);
    if (st.pan) { st.pan = null; return setCursor("crosshair"); }
    if (e.button === 0) soltar(cx);
  });
  lienzo.addEventListener("pointerleave", () => { if (!st.drag && !st.pan) { st.cursor = null; estado(); } });

  function presionar(cx, cy) {
    const ls = lineasFrame();
    if (st.modo === "nueva") {
      const p = canvasAImg(cx, cy);
      if (!p) return;
      st.drag = { tipo: "nueva", x0: p[0], x1: p[0], y: p[1], cx0: cx };
      return dibujar();
    }
    if (st.modo === "eliminar") {
      const hit = buscarAncla(cx, cy);
      if (hit) {
        const [i, j] = hit;
        if (ls[i].anclas.length <= 2) {
          return estado("Una línea necesita al menos 2 anclas. Para borrar la línea, haz clic sobre ella fuera de las anclas.");
        }
        guardarHistorial();
        ls[i].anclas.splice(j, 1);
        return marcarCambio("Ancla eliminada.");
      }
      const i = buscarLinea(cx, cy);
      if (i === null) return estado("No hay ninguna línea ni ancla cerca del clic.");
      guardarHistorial();
      ls.splice(i, 1);
      st.sel = null;
      return marcarCambio("Línea eliminada.");
    }
    // modo edición
    const hit = buscarAncla(cx, cy);
    if (hit) {
      st.sel = hit[0];
      guardarHistorial();
      st.drag = { tipo: "ancla", i: hit[0], j: hit[1], movido: false };
    } else {
      const i = buscarLinea(cx, cy);
      if (i !== null) {
        st.sel = i;
        guardarHistorial();
        st.drag = { tipo: "linea", i, y0: canvasAImgLibre(cx, cy)[1], altura0: ls[i].altura, movido: false };
      } else st.sel = null;
    }
    actualizarAlturaUI(true);
    estado();
    dibujar();
  }

  function arrastrar(cx, cy) {
    const d = st.drag;
    const { ancho: w, alto: h } = st.video;
    let [x, y] = canvasAImgLibre(cx, cy);
    if (d.tipo === "nueva") { d.x1 = r1(clamp(x, 0, w - 1)); return dibujar(); }
    const l = lineasFrame()[d.i];
    if (d.tipo === "ancla") {
      const a = l.anclas, j = d.j;
      const xmin = j > 0 ? a[j - 1].x + SEP_MIN_ANCLAS : 0;
      const xmax = j < a.length - 1 ? a[j + 1].x - SEP_MIN_ANCLAS : w - 1;
      x = clamp(x, xmin, xmax);
      y = clamp(y, 0, h - 1);
      a[j] = { x: r1(x), dy: r1(y - l.altura) };
    } else {
      l.altura = r1(limitarAltura(l, d.altura0 + (y - d.y0)));
    }
    d.movido = true;
    st.cursor = canvasAImg(cx, cy);
    actualizarAlturaUI(true);
    estado();
    dibujar();
  }

  function soltar(cx) {
    const d = st.drag;
    st.drag = null;
    if (!d) return;
    if (d.tipo === "nueva") {
      const w = st.video.ancho;
      let x0, x1;
      if (Math.abs(cx - d.cx0) < TRAMO_MIN_PANTALLA) { x0 = 0; x1 = w - 1; }
      else [x0, x1] = [d.x0, d.x1].sort((a, b) => a - b);
      if (x1 - x0 < ANCLAS_INICIALES - 1) {
        estado("El tramo es demasiado corto; arrastra más o haz un clic simple.");
        return dibujar();
      }
      guardarHistorial();
      const anclas = G.linspace(x0, x1, ANCLAS_INICIALES).map((x) => ({ x: r1(x), dy: 0 }));
      lineasFrame().push({ altura: d.y, anclas });
      st.sel = ordenarLineas(lineasFrame().length - 1);
      cambiarModo(null, true);
      return marcarCambio("Línea creada. Arrastra las anclas para darle curvatura o la línea para cambiar su altura.");
    }
    if (d.movido) marcarCambio(); else descartarHistorial();
  }

  function dobleClic(cx, cy) {
    if (st.modo !== null || !st.video || buscarAncla(cx, cy)) return;
    const i = buscarLinea(cx, cy);
    if (i === null) return;
    const l = lineasFrame()[i];
    let [x] = canvasAImgLibre(cx, cy);
    const [x0, x1] = G.lineaRango(l);
    if (!(x > x0 && x < x1)) return estado("Para alargar la línea, arrastra el ancla del extremo.");
    x = r1(x);
    if (Math.min(...l.anclas.map((a) => Math.abs(a.x - x))) < SEP_MIN_ANCLAS) return;
    const dy = r1(G.lineaY(l, [x])[0] - l.altura);
    guardarHistorial();
    l.anclas.push({ x, dy });
    l.anclas.sort((a, b) => a.x - b.x);
    st.sel = i;
    marcarCambio("Ancla agregada.");
  }

  // ---------------------------------------------------------------- teclado
  document.addEventListener("keydown", (e) => {
    if (dlg.open) return;
    const enCampo = ["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName);
    const ctrl = e.ctrlKey || e.metaKey;
    if (ctrl && e.key.toLowerCase() === "s") { e.preventDefault(); abrirDescarga(); return; }
    if (enCampo) return;
    if (ctrl && e.key.toLowerCase() === "z") { e.preventDefault(); return deshacer(); }
    if (ctrl) return;
    const acciones = {
      ArrowLeft: () => irA(st.frame - 1),
      ArrowRight: () => irA(st.frame + 1),
      ArrowUp: () => moverAltura(e.shiftKey ? -0.1 : -1),
      ArrowDown: () => moverAltura(e.shiftKey ? 0.1 : 1),
      Delete: eliminarSeleccionada,
      Escape: () => cambiarModo(null, true),
      "+": () => zoomEn(ZOOM_PASO),
      "=": () => zoomEn(ZOOM_PASO),
      "-": () => zoomEn(1 / ZOOM_PASO),
      0: ajustarVista,
    };
    const f = acciones[e.key];
    if (f) { e.preventDefault(); f(); }
  });

  // ------------------------------------------------------------------ dibujo
  let rafPendiente = false;
  function dibujar() {
    if (rafPendiente) return;
    rafPendiente = true;
    requestAnimationFrame(() => { rafPendiente = false; render(); });
  }

  function redimensionar() {
    const dpr = window.devicePixelRatio || 1;
    const [cw, ch] = tam();
    lienzo.width = Math.max(1, Math.round(cw * dpr));
    lienzo.height = Math.max(1, Math.round(ch * dpr));
    lienzo.style.width = `${cw}px`;
    lienzo.style.height = `${ch}px`;
    render();
  }
  new ResizeObserver(redimensionar).observe(cont);

  function render() {
    const dpr = window.devicePixelRatio || 1;
    const [cw, ch] = tam();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, cw, ch);
    const v = st.video;
    if (!v || !st.imgBloque || cw < 2 || ch < 2) return;

    const sFit = Math.min(cw / v.ancho, ch / v.alto);
    if (st.ajustado || st.escala <= sFit) { st.ajustado = true; st.escala = sFit; }
    limitarVista();
    const s = st.escala, [ox, oy] = st.off;
    $("lbl-zoom").textContent = `${Math.round(s * 100)}%`;

    // Frame: se toma su celda dentro de la imagen del bloque. Con zoom se ve cada píxel real.
    const pos = st.frame % v.bloque;
    const sx = (pos % v.columnas) * v.ancho, sy = Math.floor(pos / v.columnas) * v.alto;
    ctx.imageSmoothingEnabled = s < 1;
    ctx.drawImage(st.imgBloque.img, sx, sy, v.ancho, v.alto, ox, oy, v.ancho * s, v.alto * s);

    // Líneas y anclas
    const ls = st.lineas.get(st.frame) || [];
    const xv0 = -ox / s - 1, xv1 = (cw - ox) / s;
    const r = clamp(s * 1.2, 3, 6);
    ctx.lineJoin = "round";
    ls.forEach((l, i) => {
      const col = COLORES[i % COLORES.length];
      const sel = i === st.sel;
      const [a0, a1] = G.lineaRango(l);
      const v0 = Math.max(a0, xv0), v1 = Math.min(a1, xv1);
      if (v1 > v0) {
        const n = Math.max(2, Math.floor(((v1 - v0) * s) / 2) + 2);
        const xs = G.linspace(v0, v1, n);
        const ys = G.lineaY(l, xs);
        ctx.beginPath();
        xs.forEach((x, k) => { const [px, py] = imgACanvas(x, ys[k]); k ? ctx.lineTo(px, py) : ctx.moveTo(px, py); });
        ctx.strokeStyle = col;
        ctx.lineWidth = sel ? 3 : 1.5;
        ctx.setLineDash([]);
        ctx.stroke();
      }
      ctx.lineWidth = 2;
      for (const a of l.anclas) {
        const [ax, ay] = imgACanvas(a.x, l.altura + a.dy);
        if (sel) { ctx.fillStyle = col; ctx.fillRect(ax - r, ay - r, 2 * r, 2 * r); }
        ctx.strokeStyle = col;
        ctx.strokeRect(ax - r, ay - r, 2 * r, 2 * r);
      }
      const [lx, ly] = imgACanvas(a0, l.altura + l.anclas[0].dy);
      texto(`L${i + 1}`, lx - r - 4, ly, col, "right");
    });

    for (const p of G.distanciasConsecutivas(ls)) {
      const xm = p.cols[Math.floor(p.cols.length / 2)];
      const [px, pya] = imgACanvas(xm, G.lineaY(ls[p.a], [xm])[0]);
      const [, pyb] = imgACanvas(xm, G.lineaY(ls[p.b], [xm])[0]);
      ctx.beginPath();
      ctx.moveTo(px, pya); ctx.lineTo(px, pyb);
      ctx.strokeStyle = "#fff"; ctx.lineWidth = 1; ctx.setLineDash([3, 3]); ctx.stroke(); ctx.setLineDash([]);
      texto(`L${p.a + 1}–L${p.b + 1}: ${G.media(p.d).toFixed(1)} px`, px + 6, (pya + pyb) / 2, "#fff", "left");
    }

    const d = st.drag;
    if (d && d.tipo === "nueva") {
      let x0 = 0, x1 = v.ancho - 1;
      if (Math.abs(d.x1 - d.x0) * s >= TRAMO_MIN_PANTALLA) [x0, x1] = [d.x0, d.x1].sort((a, b) => a - b);
      const [p0x, p0y] = imgACanvas(x0, d.y), [p1x] = imgACanvas(x1, d.y);
      ctx.beginPath(); ctx.moveTo(p0x, p0y); ctx.lineTo(p1x, p0y);
      ctx.strokeStyle = COLORES[ls.length % COLORES.length]; ctx.lineWidth = 2; ctx.setLineDash([6, 4]);
      ctx.stroke(); ctx.setLineDash([]);
    }
  }

  function texto(t, x, y, col, align) {
    ctx.font = "600 12px system-ui, -apple-system, 'Segoe UI', sans-serif";
    ctx.textAlign = align;
    ctx.textBaseline = "middle";
    ctx.lineWidth = 3;
    ctx.strokeStyle = "rgba(0,0,0,.8)";
    ctx.strokeText(t, x, y);
    ctx.fillStyle = col;
    ctx.fillText(t, x, y);
  }

  // ------------------------------------------------------------------ estado
  function estado(msg) {
    if (msg === undefined) {
      const v = st.video;
      if (!v) return;
      const ls = st.lineas.get(st.frame) || [];
      const partes = [`Frame ${st.frame}/${v.n_frames - 1}`];
      if (v.fps) partes.push(`t = ${(st.frame / v.fps).toFixed(2)} s`);
      if (st.cargando) partes.push("cargando…");
      partes.push(`${ls.length} línea${ls.length === 1 ? "" : "s"}`);
      for (const p of G.distanciasConsecutivas(ls)) partes.push(`L${p.a + 1}–L${p.b + 1} media ${G.media(p.d).toFixed(2)} px`);
      if (selValida()) { const l = ls[st.sel]; partes.push(`L${st.sel + 1}: altura ${l.altura.toFixed(1)}, ${l.anclas.length} anclas`); }
      if (st.modo === "nueva") partes.push("NUEVA LÍNEA: clic = borde a borde · clic y arrastrar = solo ese tramo");
      else if (st.modo === "eliminar") partes.push("ELIMINAR: clic en un ancla la quita · clic en la línea la borra");
      else if (!ls.length) partes.push("pulsa «Nueva línea» para empezar");
      else partes.push("arrastra anclas (curvatura) o la línea (altura) · doble clic: +ancla");
      if (st.cursor) partes.push(`x=${st.cursor[0].toFixed(1)} y=${st.cursor[1].toFixed(1)}`);
      msg = partes.join("   ·   ");
    }
    $("estado").textContent = msg;
  }

  actualizarIndicador();
  // Para pruebas automatizadas.
  return { st, irA, zoomEn, guardarTodo };
}

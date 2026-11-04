# Anotador de bordes de la arteria braquial

Herramienta web para trazar las paredes de la arteria braquial frame por frame. Es la versión
web de `ground_truth/anotador_frames_v2.py`: usa las mismas líneas curvables (altura + anclas,
interpolación PCHIP) y produce los mismos datos.

**Link para anotadores:** <https://kenneths0.github.io/ArteryBorderAnnotator/>

No hace falta cuenta ni instalar nada. Cada persona elige un video y los frames que quiera,
anota, y al terminar descarga un archivo y lo envía al equipo.

## Para los anotadores

1. Abre el link y elige un video arriba a la izquierda.
2. Ve al frame que quieras: escríbelo en el cuadro de número + Enter, o usa ◀ ▶ / ← →.
   La meta es unos 25 frames por video.
3. Anota el frame de **una** de estas dos formas (no las dos en el mismo frame):

   **A. Líneas** — **Nueva línea** + clic sobre la pared superior de la arteria; repite para la
   inferior. La línea va de borde a borde; para que cubra solo un tramo, haz clic y arrastra en
   horizontal. Luego ajusta cada línea al borde (paso 4).

   **B. Pares de puntos** — **Marcar puntos**, clic en una pared y clic en la otra: el segundo
   punto queda en la misma columna que el primero. Repite en distintas posiciones a lo largo de la
   arteria: **mínimo 10 pares por frame**. El modo queda activo para seguir marcando; Esc cancela
   un punto a medias. Para ajustar un punto, arrástralo (solo se mueve en vertical).

4. Para ajustar las líneas:
   - Arrastrar un ancla (los cuadritos) le da curvatura.
   - Arrastrar la línea la sube o la baja completa. También puedes usar ↑/↓ (Shift: 0.1 px)
     o escribir la altura.
   - Doble clic sobre la línea agrega un ancla.
   - Usa la rueda del mouse para hacer zoom y clic derecho + arrastrar para moverte.
5. Al terminar, pulsa **Descargar anotaciones**, escribe tu nombre y **envía el archivo**
   `anotaciones_<tu_nombre>_<fecha>.json` al equipo.

El panel derecho cuenta los frames **completos** (2 líneas, o 10 pares de puntos o más) y marca
en ámbar los que no lo están. Al descargar se avisa si algún frame tiene menos de 10 pares.

Tu trabajo se guarda en el navegador mientras anotas, así que recargar la página no lo borra.
Pero **solo vive en ese navegador y esa computadora**: hasta que no descargas y envías el archivo,
el equipo no lo tiene. Si borras los datos del navegador, se pierde. Para seguir otro día o en
otra computadora, usa **Cargar archivo** con el último archivo que descargaste.

| Acción | Cómo |
|---|---|
| Par de puntos | **Marcar puntos** + clic en un borde + clic en el otro (mín. 10 por frame) |
| Ajustar un punto | arrastrarlo (en vertical) |
| Curvatura | arrastrar un ancla |
| Altura | arrastrar la línea · ↑/↓ (Shift 0.1 px) · campo **Altura** + Enter |
| Agregar ancla | doble clic sobre la línea |
| Quitar ancla / punto / línea | **Eliminar** + clic en el ancla, el punto o la línea · Supr borra la línea seleccionada |
| Deshacer | Ctrl+Z |
| Zoom / mover la vista | rueda del mouse / clic derecho + arrastrar · tecla 0 para ajustar |
| Descargar | botón **Descargar anotaciones** o Ctrl+S |

## Para el equipo: juntar los resultados

Guarda los archivos que te envíen en una carpeta, por ejemplo `recibidos/`, que está en el
`.gitignore`. Luego:

```bash
pip install -r scripts/requirements.txt
python scripts/importar_anotaciones.py recibidos/ --videos ../videos
```

Crea `ground_truth_web/` con:

- `<video>_ground_truth/<persona>/<frame>/frame_<n>.json`, `_original.png` y `_anotado.png`:
  el mismo formato `lineas_v2` que exporta `anotador_frames_v2.py` (curva por columna,
  distancias, diámetro medio…), más quién anotó.
- `resumen_anotaciones.csv`: una fila por anotación, con el diámetro medio, mediana, mín, máx y
  desviación. Sirve para comparar con `arteria_braquial.py` y entre anotadores.

`--videos` apunta a la carpeta con los `.avi` originales, de donde salen los PNG. Con
`--sin-imagenes` solo se escribe el CSV. Si una persona envía varios archivos, por cada frame se
usa la versión editada más recientemente.

### Líneas numéricas para comparar con la detección

`scripts/lineas_anotadas.py` reconstruye cada línea anotada con el mismo cálculo que usa la
página para dibujarla. Devuelve las paredes con la misma forma que las de
`deteccion_bordes.py`: un valor por columna `x` y `NaN` fuera del tramo anotado. Para los frames
anotados con pares de puntos, `a.puntos()` da las coordenadas exactas de cada par, y
`comparar_paredes` evalúa la detección en la `x` exacta de cada par, interpolando entre
columnas. Los frames incompletos (menos de 10 pares, o líneas que no son exactamente 2) se
descartan con un aviso.

```python
from lineas_anotadas import cargar_anotaciones, comparar_paredes

for a in cargar_anotaciones("recibidos/"):
    sup, inf = a.paredes()                         # arreglos de largo a.ancho (330)
    m = comparar_paredes(a, sup_detectada, inf_detectada)
    print(a.video, a.frame, a.anotador, m["diametro"]["mae_px"])
```

Desde la terminal: `python scripts/lineas_anotadas.py recibidos/` escribe `paredes_anotadas.csv`,
con una fila por columna (líneas) o por par de puntos (`tipo, x, y_superior, y_inferior,
diametro_px`). Si agregas
`--imagenes verificacion --videos ../videos`, dibuja cada anotación sobre su frame para
compararla a ojo con la página. También lee los `frame_<n>.json` de la versión de escritorio.

Validación: con anotaciones reales hechas en la página, los valores de Python coinciden
exactamente (diferencia 0) con los de `js/geometria.js` en todas las columnas y en cada ancla.
Además, midiendo los píxeles dibujados en pantalla con zoom ×20, la diferencia en 140 columnas
fue de 0.008 px como máximo. Los pares de puntos del archivo son exactamente los marcados, y su
posición en pantalla coincide con la del archivo (24 puntos medidos, diferencia 0).

### Formato del archivo que envían

```json
{
  "formato": "anotaciones_web_v1",
  "anotador": "María José Pérez",
  "exportado": "2026-10-27T03:43:10Z",
  "videos": {
    "VTS_01_2": {
      "ancho": 330, "alto": 320, "n_frames": 3743, "fps": 29.97,
      "frames": {
        "0": {
          "actualizado": "…",
          "lineas": [
            {"altura": 102.1, "anclas": [{"x": 0.0, "dy": 0.0}, {"x": 74.9, "dy": 3.9}, …]},
            {"altura": 129.5, "anclas": […]}
          ]
        },
        "5": {
          "actualizado": "…",
          "lineas": [],
          "pares": [
            {"x": 26.0, "y_superior": 99.6, "y_inferior": 130.5},
            {"x": 39.0, "y_superior": 102.7, "y_inferior": 128.7},
            …
          ]
        }
      }
    }
  }
}
```

Son exactamente los datos fuente de la versión de escritorio: `y_ancla = altura + dy`, con las
líneas ordenadas de arriba hacia abajo. Los `pares` (opcionales) están ordenados por `x`, con
`y_superior < y_inferior`. `importar_anotaciones.py` exporta los frames con pares en formato
`pares_v1`, con mediciones `punto_superior` / `punto_inferior` / `distancia_px`. Frames desde 0, en píxeles de la imagen original.

## Cómo están los videos en el sitio

El navegador no puede reproducir los `.avi` y tampoco garantiza ubicarse exactamente en un
frame dado. Por eso `scripts/preparar_frames.py` extrae los frames con OpenCV, en el mismo orden
que `arteria_braquial.py`, y los guarda en `frames/<video>/` en bloques de 25 frames: imágenes
WebP **sin pérdida** de 5×5 frames. Los píxeles son idénticos al original (verificado frame por
frame), y el frame N de la web es el frame N de los otros programas. Son ~330 MB en total.

Para agregar o regenerar un video:

```bash
python scripts/preparar_frames.py ../videos/VTS_01_6.avi
git add frames && git commit -m "Agregar VTS_01_6" && git push
```

> OpenCV reporta un frame más del que realmente se puede leer en cada video (p. ej. 3744 en
> lugar de 3743). La web usa el conteo real.

## Archivos

| Archivo | Qué es |
|---|---|
| `index.html`, `css/estilos.css` | la página |
| `js/app.js` | la interfaz: dibujo, edición, zoom |
| `js/geometria.js` | PCHIP, curvas y distancias: traducción exacta del código Python (verificada con 201 casos, diferencia 0) |
| `js/almacen-local.js` | respaldo en el navegador, descargar y cargar archivos |
| `js/config.js` | meta de frames por video |
| `frames/` | los frames de los videos y `videos.json` |
| `scripts/preparar_frames.py` | `.avi` → `frames/` |
| `scripts/importar_anotaciones.py` | archivos recibidos → formato de escritorio + CSV |
| `scripts/lineas_anotadas.py` | archivos recibidos → paredes por columna para comparar con la detección |
| `scripts/formato_ground_truth.py` | geometría y exportación compartidas con la versión de escritorio |

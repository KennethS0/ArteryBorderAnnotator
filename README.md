# Anotador de bordes de la arteria braquial

Herramienta web para trazar las paredes de la arteria braquial frame por frame. Es la versión
web de `ground_truth/anotador_frames_v2.py`: usa las mismas líneas curvables (altura + anclas,
interpolación PCHIP) y produce los mismos datos.

**Link para anotadores:** <https://kenneths0.github.io/ArteryBorderAnnotator/>

No hace falta cuenta ni instalar nada. Cada persona elige un video y los frames que quiera,
anota, y al terminar descarga un archivo y lo envía al equipo.

## Para los anotadores

1. Abre el link y elige un video arriba a la izquierda, o pulsa **Abrir video…** para abrir un
   `.avi` de tu computadora (también puedes arrastrarlo a la página; no se sube a ningún lado).
2. Ve al frame que quieras: escríbelo en el cuadro de número + Enter, o usa ◀ ▶ / ← →.
   La meta es unos 25 frames por video.
3. Anota el frame con líneas, con pares de puntos o con ambos. Con el selector **Líneas | Puntos**
   de la barra (o las teclas L / P) eliges qué ves y editas: cada vista oculta lo de la otra.

   **A. Líneas** (vista Líneas) — **Nueva línea** + clic sobre la pared superior de la arteria; repite para la
   inferior. La línea va de borde a borde; para que cubra solo un tramo, haz clic y arrastra en
   horizontal. Luego ajusta cada línea al borde (paso 4).

   **B. Pares de puntos** (vista Puntos) — **Marcar puntos**, clic en una pared y clic en la otra: el segundo
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

El panel derecho cuenta los frames **completos** (2 líneas, o 10 pares de puntos o más), muestra
lo que tiene cada frame (p. ej. `30.0 px · 10 pts`) y marca en ámbar lo incompleto. Al descargar se avisa si algún frame tiene menos de 10 pares.

Tu trabajo se guarda en el navegador mientras anotas, así que recargar la página no lo borra.
Pero **solo vive en ese navegador y esa computadora**: hasta que no descargas y envías el archivo,
el equipo no lo tiene. Si borras los datos del navegador, se pierde. Para seguir otro día o en
otra computadora, usa **Cargar archivo** con el último archivo que descargaste.

| Acción | Cómo |
|---|---|
| Cambiar de vista | selector **Líneas / Puntos** o teclas L / P |
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
`deteccion_bordes.py`: un valor por columna `x` y `NaN` fuera del tramo anotado. Un frame puede tener líneas y pares a la vez: `paredes()`,
`comparar_paredes()` y `resumen()` aceptan `fuente="lineas"` o `fuente="pares"`. Si no se
indica, usan las líneas cuando hay 2, y si no, los pares. `a.puntos()` da las coordenadas exactas
de cada par, y con `fuente="pares"` la detección se evalúa en la `x` exacta de cada par,
interpolando entre columnas. Lo incompleto (menos de 10 pares, o líneas que no son exactamente 2)
se descarta con un aviso, sin perder el otro tipo del mismo frame.

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
          "lineas": [ … ],
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
`y_superior < y_inferior`. `importar_anotaciones.py` exporta los pares en formato `pares_v1` (`frame_<n>_pares.json`,
con mediciones `punto_superior` / `punto_inferior` / `distancia_px`), junto a los archivos de
líneas del mismo frame. El CSV tiene una fila por frame, persona y tipo. Frames desde 0, en píxeles de la imagen original.

## Cómo están los videos en el sitio

El navegador no puede reproducir los `.avi` y tampoco garantiza ubicarse exactamente en un
frame dado. Por eso `scripts/preparar_frames.py` extrae los frames con OpenCV, en el mismo orden
que `arteria_braquial.py`, y los guarda en `frames/<video>/` en bloques de 25 frames: imágenes
WebP **sin pérdida** de 5×5 frames. Los píxeles son idénticos al original (verificado frame por
frame), y el frame N de la web es el frame N de los otros programas. Son ~330 MB en total, y el
sitio de GitHub Pages no puede pasar de 1 GB. Por eso los demás videos no se suben: se abren
desde la computadora (ver abajo).

Para agregar o regenerar un video del sitio:

```bash
python scripts/preparar_frames.py ../videos/VTS_01_6.avi
git add frames && git commit -m "Agregar VTS_01_6" && git push
```

> OpenCV reporta un frame más del que realmente se puede leer en cada video (p. ej. 3744 en
> lugar de 3743). La web usa el conteo real.

## Videos desde la computadora (sin subirlos)

**Abrir video…** (o arrastrar el archivo a la página) abre un `.avi` local. El archivo **no se
sube a ningún lado**: `js/avi-local.js` recorre el contenedor AVI, anota dónde está cada frame
y lee solo el que se pide. Así se puede ir a cualquier frame exacto, sin cargar el video entero
en memoria. Las anotaciones quedan con el nombre del archivo sin `.avi` (p. ej.
`DVD1_VTS_01_2`), igual que en los otros programas. Al recargar la página hay que volver a abrir
el archivo. Un enlace `#v=DVD1_VTS_01_2&f=1500` lleva a ese frame en cuanto se abre el archivo.

| Códec del `.avi` | Píxeles comparados con OpenCV |
|---|---|
| PNG (`recortar_vob_a_avi.py --codec png`, ~450 MB por video) | idénticos (diferencia 0) |
| sin compresión (BI_RGB 24/32 bits) | idénticos (diferencia 0) |
| MJPEG (`recortar_vob_a_avi.py`, por defecto, ~70 MB por video) | casi iguales: en gris, 0.1 niveles en promedio y 2 como máximo (los decodificadores JPEG redondean distinto) |

El número de frames y la numeración coinciden siempre con OpenCV: los fragmentos de video
vacíos que escribe ffmpeg se saltan, igual que hace OpenCV. Verificado en Chromium contra
`cv2.VideoCapture` con los 4 tipos de archivo, incluido un video con 14 fragmentos vacíos.
Otros códecs (FFV1, H.264…) no se pueden leer: hay que convertirlos con
`recortar_vob_a_avi.py` o `ffmpeg -i entrada -c:v png -pix_fmt rgb24 salida.avi`.

## Archivos

| Archivo | Qué es |
|---|---|
| `index.html`, `css/estilos.css` | la página |
| `js/app.js` | la interfaz: dibujo, edición, zoom |
| `js/geometria.js` | PCHIP, curvas y distancias: traducción exacta del código Python (verificada con 201 casos, diferencia 0) |
| `js/almacen-local.js` | respaldo en el navegador, descargar y cargar archivos |
| `js/config.js` | meta de frames por video |
| `js/avi-local.js` | lector de `.avi` locales (MJPEG, PNG o sin compresión) |
| `frames/` | los frames de los videos y `videos.json` |
| `scripts/preparar_frames.py` | `.avi` → `frames/` |
| `scripts/importar_anotaciones.py` | archivos recibidos → formato de escritorio + CSV |
| `scripts/lineas_anotadas.py` | archivos recibidos → paredes por columna para comparar con la detección |
| `scripts/formato_ground_truth.py` | geometría y exportación compartidas con la versión de escritorio |

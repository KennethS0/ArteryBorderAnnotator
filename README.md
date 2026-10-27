# Anotador web de la arteria braquial

Versión web de `ground_truth/anotador_frames_v2.py`. Cualquier persona autorizada abre un link,
entra con su cuenta de Google y traza las paredes de la arteria con las mismas líneas curvables
(altura + anclas, interpolación PCHIP) que la herramienta de escritorio. Las anotaciones se
guardan solas en Firebase, y un script las baja **exactamente en el mismo formato** que exporta
la versión de escritorio.

```
GitHub Pages ── index.html, css/, js/       (la herramienta; pública, sin datos)
     │
     ├── Firebase Authentication            login con Google
     ├── Cloud Firestore                    anotadores autorizados · videos · anotaciones
     └── Cloud Storage                      frames (solo visibles con sesión iniciada)

scripts/preparar_frames.py      .avi → bloques de frames → Storage + Firestore   (una vez)
scripts/descargar_anotaciones.py  Firestore → <video>_ground_truth/... + CSV     (cuando quieras)
```

## Qué datos van a dónde

| Dato | Dónde | Quién puede verlo |
|---|---|---|
| Código de la herramienta | GitHub Pages | cualquiera con el link (no contiene datos) |
| Frames de los videos | Cloud Storage `frames/<video>/bloque_NNNN.webp` | solo cuentas en la lista de anotadores |
| Lista de anotadores | Firestore `anotadores/<correo>` | se edita solo desde la consola |
| Datos de cada video | Firestore `videos/<video>` | anotadores (solo lectura) |
| Anotaciones | Firestore `anotaciones/<video>__<frame>__<uid>` | cada persona solo las suyas |

**Los videos nunca van al repositorio.** Un sitio de GitHub Pages es público aunque el repo sea
privado. Por eso los frames se sirven desde Storage, protegidos por `storage.rules`.

Cada anotación guarda exactamente los datos fuente de la versión de escritorio:

```json
{
  "video": "VTS_01_2", "frame": 1234, "uid": "…", "email": "persona@gmail.com", "nombre": "…",
  "ancho": 330, "alto": 320, "formato": "lineas_v2", "actualizado": "<fecha del servidor>",
  "lineas": [
    {"altura": 102.1, "anclas": [{"x": 0.0, "dy": 0.0}, {"x": 74.9, "dy": 3.9}, …]},
    {"altura": 129.5, "anclas": [ … ]}
  ]
}
```

### Por qué los frames van en bloques

Los 4 videos suman ~15 000 frames de 330×320. `preparar_frames.py` los lee con OpenCV en el
mismo orden que `arteria_braquial.py` y que la versión de escritorio. Los agrupa de 25 en 25 en
imágenes **WebP sin pérdida** de 5×5 frames: ~600 archivos y ~345 MB en total. Los píxeles son
idénticos al original (verificado frame por frame), y el frame N de la web es el frame N de los
otros programas. Subir 15 000 archivos sueltos excedería las 5 000 subidas mensuales sin costo
de Storage, y además haría lenta la navegación.

> Nota: OpenCV reporta un frame más del que realmente se puede leer en cada video
> (p. ej. 3744 en lugar de 3743). La web usa el conteo real.

## Costos

Firebase Storage **requiere el plan Blaze** (pago por uso, con tarjeta), pero este proyecto
cabe dentro de la cuota sin costo, siempre que el bucket esté en `us-central1`, `us-east1` o
`us-west1`:

| Servicio | Cuota sin costo | Uso estimado |
|---|---|---|
| Storage: almacenamiento | 5 GB-mes | ~0.35 GB |
| Storage: descarga | 100 GB/mes | ~0.35 GB por persona que recorra los 4 videos completos |
| Storage: subidas | 5 000/mes | ~600 una sola vez |
| Firestore | 50 000 lecturas y 20 000 escrituras por día | decenas a cientos por persona y sesión |
| Authentication (Google) | 50 000 usuarios activos/mes | unas pocas personas |

Crea una **alerta de presupuesto** (p. ej. de US$1) en Google Cloud → Facturación →
Presupuestos y alertas, para enterarte si algo se sale de lo esperado.

## Puesta en marcha (una sola vez)

### 1. Proyecto de Firebase

1. En <https://console.firebase.google.com> crea un proyecto. Google Analytics no hace falta.
2. **Plan Blaze:** ⚙ → Uso y facturación → Detalles y configuración → Modificar plan → Blaze.
   Luego crea la alerta de presupuesto.
3. **Authentication** → Comenzar → Método de acceso → **Google** → Habilitar.
   En **Configuración → Dominios autorizados**, agrega `TU-USUARIO.github.io`
   (`localhost` ya viene incluido para probar en tu computadora).
4. **Firestore Database** → Crear base de datos → modo de producción → región `us-central1`
   (o la misma que uses para Storage).
5. **Storage** → Comenzar → modo de producción → región `us-central1`.
6. **Reglas:**
   - Firestore → Reglas: pega el contenido de `firestore.rules` → Publicar.
   - Storage → Reglas: pega el contenido de `storage.rules` → Publicar. La consola te pedirá
     permiso para que Storage consulte Firestore (lo necesita para revisar la lista de
     anotadores): acéptalo.

   Alternativa con la CLI: `npm i -g firebase-tools`, `firebase login`,
   `firebase use --add` y luego `firebase deploy --only firestore:rules,storage`.
7. **App web:** ⚙ Configuración del proyecto → Tus apps → `</>` → registra la app (sin Hosting) →
   copia el objeto `firebaseConfig` en `js/config.js`. Esos valores no son secretos: lo que
   protege los datos son las reglas.
8. **Clave de administrador** (solo para los scripts, y solo en tu computadora):
   ⚙ → Cuentas de servicio → Generar nueva clave privada → guárdala como
   `clave-servicio.json` en esta carpeta. Está en `.gitignore`: **nunca la subas ni la compartas.**

### 2. Autorizar anotadores

Firestore → Iniciar colección `anotadores` → un documento por persona:

- **ID del documento:** su correo de Google, en minúsculas (p. ej. `ken.sanchez0609@gmail.com`).
- Campos: no necesita ninguno. Puedes agregar `nombre` si quieres.

Para quitarle el acceso a alguien, borra su documento.

### 3. Subir los frames

```bash
pip install -r scripts/requirements.txt
python scripts/preparar_frames.py ../videos --subir \
    --credenciales clave-servicio.json --bucket TU-PROYECTO.firebasestorage.app
```

El nombre del bucket aparece arriba en la pestaña Storage de la consola (sin `gs://`).
Comprimir tarda ~10–15 min para los 4 videos. Si se corta, vuélvelo a correr: los bloques que
ya se subieron se saltan. Sin `--subir`, solo genera los bloques en `frames_web/` para revisarlos.

### 4. Publicar en GitHub Pages

Esta carpeta (`anotador_web/`) es el repositorio. No tiene videos ni datos.

```bash
cd anotador_web
git init && git add . && git commit -m "Anotador web"
git branch -M main
git remote add origin https://github.com/TU-USUARIO/anotador-arteria.git
git push -u origin main
```

En GitHub: Settings → Pages → Source: **Deploy from a branch** → `main` / `(root)` → Save.
En uno o dos minutos queda en `https://TU-USUARIO.github.io/anotador-arteria/`.

Para probar antes en tu computadora: `python -m http.server 8000` dentro de esta carpeta y abre
<http://localhost:8000>. Tiene que ser por un servidor; abrir el `index.html` con doble clic no
funciona, porque los módulos de JavaScript necesitan `http://`.

## Uso (para los anotadores)

Comparte el link. Cada persona entra con Google, elige el video y anota los frames que quiera.
El panel de la derecha muestra cuántos lleva (meta: 25 por video) y permite volver a cualquiera.
Los cambios se guardan solos un segundo y medio después del último cambio (o con Ctrl+S). El
indicador de arriba dice si hay algo pendiente. Cada quien ve solo sus propias marcas, así que
las anotaciones son independientes.

Los controles son los mismos que en la versión de escritorio:

| Acción | Cómo |
|---|---|
| Nueva línea | botón **Nueva línea** + clic (borde a borde) o clic y arrastrar (solo ese tramo) |
| Curvatura | arrastrar un ancla |
| Altura | arrastrar la línea, escribir en **Altura** + Enter, o ↑/↓ (Shift: 0.1 px) |
| Agregar ancla | doble clic sobre la línea |
| Quitar ancla / línea | botón **Eliminar** + clic en el ancla / en la línea · Supr borra la seleccionada |
| Deshacer | Ctrl+Z |
| Navegar | ← / →, o escribir el número de frame + Enter |
| Zoom | rueda del mouse (centrado en el cursor), botones −/+, tecla 0 para ajustar |
| Mover la vista | clic derecho (o rueda presionada) + arrastrar |

La URL guarda el video y el frame (`#v=VTS_01_2&f=1234`), así que se puede compartir un link a
un frame concreto.

## Bajar los resultados

```bash
python scripts/descargar_anotaciones.py --credenciales clave-servicio.json --videos ../videos
```

Crea `ground_truth_web/` con:

- `<video>_ground_truth/<persona>/<frame>/frame_<n>.json`, `_original.png` y `_anotado.png`:
  el mismo formato `lineas_v2` que exporta `anotador_frames_v2.py` (curva por columna,
  distancias, etc.), más quién anotó y cuándo. La carpeta `<persona>` es la parte del correo
  antes de la @.
- `resumen_anotaciones.csv`: una fila por anotación, con el diámetro medio, mediana, mín, máx y
  desviación. Sirve para comparar con `arteria_braquial.py` y para medir la variabilidad entre
  anotadores cuando dos personas marcan el mismo frame.

Con `--sin-imagenes` solo escribe el CSV.

## Archivos

| Archivo | Qué es |
|---|---|
| `index.html`, `css/estilos.css` | la página |
| `js/app.js` | la interfaz: dibujo, edición, zoom, autoguardado (no depende de Firebase) |
| `js/geometria.js` | PCHIP, curvas y distancias: traducción exacta del código Python (verificada con 201 casos, diferencia 0) |
| `js/firebase-backend.js` | todo lo que habla con Firebase (SDK web 12.19.0) |
| `js/config.js` | **lo que tienes que editar**: `firebaseConfig` y la meta de frames por video |
| `firestore.rules`, `storage.rules`, `firebase.json` | reglas de seguridad |
| `scripts/` | preparar/subir frames, descargar anotaciones, formato compartido con la versión de escritorio |

## Problemas comunes

- **"Falta configurar Firebase"**: no pegaste el `firebaseConfig` en `js/config.js`.
- **`auth/unauthorized-domain` al iniciar sesión**: agrega el dominio (`TU-USUARIO.github.io`) en
  Authentication → Configuración → Dominios autorizados.
- **"La cuenta … no está autorizada"**: falta su documento en `anotadores`, o el ID no coincide
  exactamente con el correo (revisa mayúsculas y espacios).
- **No cargan los frames (`storage/unauthorized`)**: publica `storage.rules` y acepta el permiso
  para que Storage consulte Firestore. Revisa también que `preparar_frames.py --subir` haya
  terminado.
- **Se bloqueó la ventana de Google**: permite ventanas emergentes para el sitio.

> Sobre privacidad: quien tenga acceso puede, técnicamente, copiar el enlace de descarga de un
> bloque y pasárselo a otra persona. Las reglas impiden el acceso de cuentas no autorizadas,
> pero no que alguien autorizado comparta lo que ya vio. Para datos de pacientes, autoriza solo
> a personas que estén cubiertas por el protocolo del estudio.

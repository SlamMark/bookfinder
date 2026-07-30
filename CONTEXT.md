# BookFinder — Contexto del proyecto

## Objetivo
Buscar, descargar, convertir y enviar libros al Kindle automáticamente, desde
CLI o desde un bot de Telegram con control de acceso.

## Estado: las tres fases están implementadas y desplegadas

### Fase 1 — CLI ✅
Búsqueda combinada en Z-Library + Libgen con tabla de resultados y descarga
interactiva por número.

- `main.py` — entrada CLI (`--lang`, `--max`, `--libgen-only`, `--zlib-only`)
- `searcher_zlib.py` — Z-Library (se consulta primero). Dominio configurable
  con `ZLIB_DOMAIN`; ver la sección de dominios más abajo
- `searcher_libgen.py` — Libgen vía `libgen-api-enhanced` (fiction + non-fiction,
  dedup por md5, descarte de filas malformadas)
- `zlib_client.py` — cliente vendorizado de los endpoints oficiales `/eapi/`
- `covers.py` — portadas de Open Library, sólo como recurso alternativo
- `downloader.py` — resolución de URL, descarga y `fetch_image` para portadas
- `config.py` — credenciales y ajustes desde `.env`

### Fase 2 — Bot de Telegram ✅
`bot.py`. Escribes un título → resultados paginados → ficha de detalle → descarga o envío.

- **Búsqueda paginada**: 5 páginas de 8 resultados, navegación con ◀️ ▶️
- **Ficha de detalle**: portada, sinopsis, categorías, año, idioma, serie, editorial, IPFS
- **Control de acceso**: los usuarios nuevos quedan en `pending` y el admin recibe
  una notificación con botones Aprobar / Rechazar. `_check_access()` se aplica en
  todos los handlers, incluidos los callbacks
- **Onboarding**: al aprobar a un usuario se le envían las instrucciones de
  configuración de Kindle paso a paso
- **Preferencias por usuario** en `data/user_settings.json` (`user_settings.py`),
  persistido en volumen Docker: email de Kindle, formato por defecto, fuente de
  búsqueda y estado de aprobación

Comandos: `/start`, `/help`, `/myid`, `/setkindle`, `/setformat`, `/setsource`,
`/testkindle`. Registrados con `set_my_commands` para que Telegram los autocomplete.

### Fase 3 — Conversión Calibre + envío al Kindle ✅
Por **email SMTP**, no por USB (el plan original contemplaba USB; se descartó).

- `converter.py` — `ebook-convert --enable-heuristics` entre epub/mobi/azw3/pdf,
  y `ebook-meta` para inyectar título y autor correctos antes de enviar
- `mailer.py` — envío SMTP con MIME correcto (`application/epub+zip` para EPUB),
  reintentos con backoff 10s/30s, distinción entre errores permanentes
  (auth, destinatario rechazado) y transitorios, límite de 50 MB de Amazon
- `/testkindle` — envía un `.txt` de prueba para diagnosticar la configuración

**Controles de calidad antes de enviar al Kindle** (ambos bloquean el envío):
1. **Verificación de portada** — se comprueba que el EPUB declara una portada en
   el manifiesto y que el fichero existe dentro del zip. Cubre EPUB3
   (`properties="cover-image"`), EPUB2 (`<meta name="cover">`) y un fallback por
   id de item con media-type de imagen
2. **Verificación de contenido** — se comparan las metadatas OPF del fichero
   descargado con el título esperado. Z-Library sirve a veces un archivo que no
   corresponde al libro seleccionado; si no coinciden se avisa al usuario

### Despliegue ✅
- `Dockerfile` — python:3.11-slim + Calibre completo
- `docker-compose.yml` — volúmenes `./downloads` y `./data`, `restart: unless-stopped`
- `.github/workflows/deploy.yml` — en cada push a `main`: Tailscale → SSH al LXC →
  `git pull && docker compose up -d --build`

## Portadas

Orden de preferencia, implementado en `handle_detail`:

1. **La portada que trae el propio resultado** (`book["cover"]`). Ambos backends
   la dan: Z-Library en el campo `cover`, Libgen en `cover_url`. Es exacta por
   construcción, va con el registro del fichero y no hay que deducir nada
2. **Open Library** (`covers.py`) como red de seguridad, sólo si el resultado no
   trae ninguna. La ficha indica "Portada vía Open Library" cuando viene de ahí,
   porque ésa sí es una coincidencia deducida

> Durante mucho tiempo se creyó que Libgen no daba portadas. Sí las da:
> `libgen-api-enhanced` expone `cover_url` en cada `Book` y `_book_to_dict`
> simplemente no lo mapeaba. Antes de tocar nada aquí, comprobar qué trae ya el
> backend.

### Emparejamiento en Open Library

**Estricto a propósito**: una portada equivocada es peor que ninguna. Se acepta
un candidato sólo si coincide el ISBN — que identifica una edición exacta — o si
coinciden título *y* autor tras normalizar acentos, mayúsculas y puntuación.
Comprobado: "Children of Dune" recibe su propia portada y no la de "Dune".

Dos detalles no evidentes de la API:
- El parámetro `title` casa de forma casi literal, así que un título con
  subtítulo no encuentra nada. Se reintenta con el título principal y, como
  último recurso, con búsqueda libre `q=`
- El orden por relevancia es flojo: buscar "Dune" devuelve antes "Children of
  Dune". Por eso se piden 20 candidatos y se filtran, en vez de fiarse de los
  primeros

Limitaciones conocidas:
- Open Library indexa las obras mayormente por su título original, así que un
  título traducido ("El nombre del viento") no encuentra nada, porque allí es
  "The Name of the Wind". Se prefiere no mostrar portada antes que mostrar la
  de otra edición
- **Con datos de Libgen esta vía casi nunca acierta**, y no es culpa del
  emparejamiento: los títulos llegan corrompidos, con la puntuación eliminada y
  campos concatenados (`"Sapiensa brief history of humankind"`,
  `"Fahrenheit 451Diario di Fahrenheit 451"`), y los autores a veces mal
  escritos (`"Yavul Noah Harari"`). Ninguna búsqueda por título casa con eso.
  Da igual, porque Libgen ya trae su propia portada
- Libgen **no expone ISBN**: `Book` no tiene ese campo. La vía del ISBN sólo
  sirve para Z-Library, que lo pone en `identifier`

## Calidad de los datos de Libgen

Su HTML se parsea a veces con las columnas desplazadas: título vacío, sin md5 y
el tamaño metido en el campo de extensión. Esas filas no se pueden descargar y
salían como botones en blanco — una búsqueda de "Fahrenheit 451" traía 24. Se
descartan en `search_libgen` y se registra cuántas.

## Z-Library: dominios y diagnóstico

`z-library.sk` dejó de servir `/eapi/` en 2026: responde **HTTP 513** con una
página HTML de verificación anti-bot (servida por `cdn.diamwall.com`), no una
redirección. `z-lib.fm` sí devuelve JSON, y es el valor por defecto de
`ZLIB_DOMAIN`. Cuando vuelvan a rotarlo, se cambia en el `.env` sin tocar código.

Cómo se diagnosticó, por si se repite:

```bash
docker compose exec bot python -c "
import requests
for d in ['z-lib.fm','z-library.sk','1lib.sk']:
    r = requests.post(f'https://{d}/eapi/user/login', data={'email':'x','password':'y'}, timeout=15)
    print(d, r.status_code, r.headers.get('content-type'))
"
```

Un **400 con `application/json`** ante credenciales falsas es un endpoint sano.
`text/html` es un bloqueo.

Este fallo era invisible: `_get_client()` devolvía `None` en silencio, Libgen
tapaba el hueco devolviendo resultados, y el único síntoma visible era que no
salían portadas. Por eso ahora se registra cada camino de fallo, y cada búsqueda
escribe su desglose por fuente:

```
Search 'sapiens' [source=both]: 40 results (40 Z-Library, 0 Libgen)
```

Ese `0 Z-Library` es la señal de alarma.

## Gotchas aprendidos

- **Portadas**: no se le puede pasar la URL de la portada a `send_photo`, porque
  entonces son *los servidores de Telegram* los que van a buscarla y algunos CDN
  rechazan esas peticiones. Hay que descargar los bytes desde el contenedor
  (`fetch_image` en `downloader.py`) y subirlos
- **Límite de caption**: Telegram permite 4096 caracteres en un mensaje pero
  sólo 1024 en el pie de una foto. Una ficha larga hacía fallar `send_photo` en
  silencio. `_send_detail` manda la portada aparte cuando el texto no cabe
- **`callback.answer()` sólo cuenta una vez** por consulta: si se responde al
  principio del handler, un segundo `answer(..., show_alert=True)` posterior se
  ignora y el botón parece muerto. Por eso `_session_books` comprueba la sesión
  *antes* de responder
- **El token del bot no debe llegar al log**: `httpx` registra la URL completa de
  cada petición a nivel INFO, y Telegram mete el token en la ruta. Se silencia
  `httpx` por debajo de WARNING y hay un filtro en el logger raíz que enmascara
  el token allá donde aparezca, para que los errores de red sigan siendo
  visibles sin filtrarlo
- **Diagnóstico general**: cuando un backend falla en silencio, otro tapa el
  hueco y el síntoma aparece en un sitio que no tiene nada que ver. Registrar
  siempre los caminos de fallo, aunque devuelvan una lista vacía "correcta"

## Infraestructura: dos incidencias resueltas

- **Tailscale devolvía 403** *"calling actor does not have enough permissions"*
  al generar la clave efímera. El cliente OAuth necesita el ámbito **Auth Keys:
  Write** y tener asignada la etiqueta que pide el workflow (`tag:ci`), que a su
  vez debe existir en `tagOwners` de la política de acceso
- **El LXC se quedó sin disco** durante un `docker compose up --build`. Son 9,8
  GB y la imagen con Calibre ocupa 5,4 GB, de los que casi nada es reciclable.
  Los despliegues que sólo tocan `.py` reutilizan capas y caben; **el día que se
  toque el `Dockerfile` o el `requirements.txt` habrá que purgar antes**
  (`docker builder prune -af && docker image prune -af`) o ampliar el disco a
  unos 20 GB, que es lo sensato

## Pendiente

- **Sesiones en memoria**: `_sessions` es un dict de proceso, así que cada
  redespliegue invalida las búsquedas abiertas. Ahora al menos el usuario recibe
  un aviso claro en vez de un botón que no hace nada, pero persistir las
  búsquedas es más complicado de lo que parece: los resultados de Libgen llevan
  dentro un `_book_obj` de `libgen-api-enhanced` que no es serializable a JSON y
  que hace falta para resolver el enlace de descarga

## Stack
- `libgen-api-enhanced` — Libgen
- Cliente Z-Library vendorizado (`zlib_client.py`, endpoints `/eapi/`) — requiere cuenta
- `python-telegram-bot` >= 20
- Calibre CLI — `ebook-convert`, `ebook-meta`
- SMTP (Gmail App Password) para el envío al Kindle
- Entorno: LXC en Proxmox, Docker, Ubuntu, Python 3.11

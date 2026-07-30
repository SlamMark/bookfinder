# BookFinder — Contexto del proyecto

## Objetivo
Buscar, descargar, convertir y enviar libros al Kindle automáticamente, desde
CLI o desde un bot de Telegram con control de acceso.

## Estado: las tres fases están implementadas y desplegadas

### Fase 1 — CLI ✅
Búsqueda combinada en Z-Library + Libgen con tabla de resultados y descarga
interactiva por número.

- `main.py` — entrada CLI (`--lang`, `--max`, `--libgen-only`, `--zlib-only`)
- `searcher_zlib.py` — Z-Library (se consulta primero)
- `searcher_libgen.py` — Libgen vía `libgen-api-enhanced` (fiction + non-fiction, dedup por md5)
- `zlib_client.py` — cliente vendorizado de los endpoints oficiales `/eapi/`
- `downloader.py` — resolución de URL + descarga con barra de progreso
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

## Gotchas aprendidos

- **Portadas**: no se le puede pasar la URL de la portada a `send_photo`, porque
  entonces son *los servidores de Telegram* los que van a buscarla y el CDN de
  Z-Library rechaza esas peticiones. Hay que descargar los bytes desde el
  contenedor (`fetch_image` en `downloader.py`) y subirlos
- **Límite de caption**: Telegram permite 4096 caracteres en un mensaje pero
  sólo 1024 en el pie de una foto. Una ficha larga hacía fallar `send_photo` en
  silencio. `_send_detail` manda la portada aparte cuando el texto no cabe
- **`callback.answer()` sólo cuenta una vez** por consulta: si se responde al
  principio del handler, un segundo `answer(..., show_alert=True)` posterior se
  ignora y el botón parece muerto. Por eso `_session_books` comprueba la sesión
  *antes* de responder

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

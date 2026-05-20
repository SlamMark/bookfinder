cat > ~/bookfinder/CONTEXT.md << 'EOF'
# BookFinder — Contexto del proyecto

## Objetivo
Script Python para buscar y descargar libros automáticamente.

## Fase 1 (completada)
CLI en Python con búsqueda en Libgen + Z-Library en cascada.
Archivos: main.py, searcher_libgen.py, searcher_zlib.py, downloader.py, config.py

## Fase 2 (pendiente)
Bot de Telegram personal: le mandas el título, te muestra botones con resultados,
pulsas uno y te envía el archivo al chat.

## Fase 3 (pendiente)
Conversión con Calibre CLI (ebook-convert) + envío al Kindle por USB.

## Stack
- libgen-api-enhanced (Libgen)
- zlibrary async (Z-Library, requiere cuenta)
- python-telegram-bot (Fase 2)
- Calibre CLI (Fase 3)
- Entorno: LXC Proxmox, Ubuntu, Python3
EOF
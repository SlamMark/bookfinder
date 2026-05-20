FROM python:3.11-slim

WORKDIR /app

# Phase 3: uncomment to add Calibre
# RUN apt-get update && apt-get install -y --no-install-recommends calibre \
#     && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Fix zlibrary: Python serializes True as "True" but Z-Library expects lowercase "true"
RUN sed -i 's/"isModal": True,/"isModal": "true",/' \
    /usr/local/lib/python3.11/site-packages/zlibrary/libasync.py

COPY . .

# Phase 1: CLI (run interactively with: docker run -it --rm --env-file .env bookfinder python main.py "query")
# Phase 2: change to CMD ["python", "bot.py"]
CMD ["python", "main.py", "--help"]

FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y calibre \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# CLI: docker run -it --rm --env-file .env bookfinder python main.py "query"
# Bot: managed by docker-compose (command: python bot.py)
CMD ["python", "bot.py"]

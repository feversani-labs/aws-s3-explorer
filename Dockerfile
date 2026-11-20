FROM python:3.12-slim

WORKDIR /app

# Instalar dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código de la aplicación
COPY app/ /app/

EXPOSE 8080

ENV PORT=8080 \
    PYTHONUNBUFFERED=1

CMD ["python3", "/app/server.py"]

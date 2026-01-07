FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY http_server.py .

EXPOSE 8080

CMD ["python", "http_server.py"]

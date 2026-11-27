FROM python:3.12-slim-bookworm
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
USER 65534
EXPOSE 8000
CMD ["gunicorn","-b","0.0.0.0:8000","--threads","4","app:app"]

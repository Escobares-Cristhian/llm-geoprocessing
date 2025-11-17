FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY gee_geoprocess.py logging_config.py .
EXPOSE 8000
CMD ["uvicorn", "gee_geoprocess:app", "--host", "0.0.0.0", "--port", "8000"]

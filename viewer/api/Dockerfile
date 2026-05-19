FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD sh -c "uvicorn main:app --host ${BIND_IP:-127.2.0.1} --port 8010 --reload"

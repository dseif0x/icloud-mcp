FROM python:3.11-slim AS build
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.11-slim
# Run as a non-root user.
RUN useradd -u 10001 -r -s /usr/sbin/nologin app
COPY --from=build /install /usr/local
COPY icloud_mcp /app/icloud_mcp
WORKDIR /app
USER 10001
ENV HOST=0.0.0.0 PORT=8080 PYTHONUNBUFFERED=1
EXPOSE 8080
ENTRYPOINT ["python", "-m", "icloud_mcp"]

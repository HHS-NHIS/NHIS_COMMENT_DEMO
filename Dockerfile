FROM python:3.12-slim
WORKDIR /site
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8080
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin nhis
COPY docs/index.html /site/index.html
COPY server.py /site/server.py
RUN chown -R nhis:nhis /site
USER nhis
EXPOSE 8080
CMD ["python", "-u", "server.py"]

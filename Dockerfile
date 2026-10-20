FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 NHIS_DEPLOYMENT_MODE=hosted NHIS_READ_ONLY=1 NHIS_PUBLIC_DEMO=1
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin nhisdemo
COPY app/ ./app/
COPY scripts/semantic_classify.py ./scripts/semantic_classify.py
COPY themes.json ./themes.json
COPY data/ ./data/
RUN python -c "import lzma,pathlib; d=pathlib.Path('data'); x=d/'comments.sqlite3.xz'; v=x.read_bytes() if x.exists() else b''.join(p.read_bytes() for p in sorted(d.glob('sqlite.part*'))); (d/'comments.sqlite3').write_bytes(lzma.decompress(v))" \
    && rm -f data/sqlite.part* data/comments.sqlite3.xz && chown -R nhisdemo:nhisdemo /app/data
USER nhisdemo
EXPOSE 8080
CMD ["python","app/server.py","--no-browser"]

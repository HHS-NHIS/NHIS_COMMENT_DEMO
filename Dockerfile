FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 NHIS_DEPLOYMENT_MODE=hosted NHIS_READ_ONLY=1 NHIS_PUBLIC_DEMO=1 NHIS_ALLOW_PUBLIC_PROVISIONAL=1
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin nhisdemo
COPY app/ ./app/
COPY scripts/semantic_classify.py ./scripts/semantic_classify.py
COPY scripts/unpack_payload.py ./scripts/unpack_payload.py
COPY scripts/verify_public_release.py ./scripts/verify_public_release.py
COPY tests/test_v107_overlay.py ./tests/test_v107_overlay.py
COPY tests/test_v107_http.py ./tests/test_v107_http.py
COPY tests/test_v108_management.py ./tests/test_v108_management.py
COPY themes.json ./themes.json
COPY VERSION.txt ./VERSION.txt
COPY tests/test_v1082.py ./tests/test_v1082.py
COPY form_letter_subjects.json ./form_letter_subjects.json
COPY payload_parts/ ./payload_parts/
RUN python scripts/unpack_payload.py \
    && python scripts/verify_public_release.py \
    && python -m unittest discover -v -s tests -p 'test_v107_*.py' \
    && python -m unittest discover -v -s tests -p 'test_v108_*.py' \
    && python -m unittest discover -v -s tests -p 'test_v1082.py' \
    && rm -rf payload_parts data/comments.sqlite3.xz \
    && chown -R nhisdemo:nhisdemo /app/data
USER nhisdemo
EXPOSE 8080
CMD ["python","app/server.py","--no-browser"]

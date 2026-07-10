# Build context is the repo root (see docker-compose.yml) since
# requirements.txt lives there, not under backend/ — matches this
# project's existing flat-import/root-requirements convention rather than
# duplicating requirements.txt into backend/.
FROM python:3.14-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Matches .github/workflows/ci.yml's own Playwright install step exactly —
# same browser (chromium), same --with-deps flag for the real OS-level
# dependencies Playwright needs (crawler.py/detector.py/verifier.py/
# page_fixer.py all launch real headless Chromium).
RUN playwright install --with-deps chromium

COPY backend/ backend/

RUN chmod +x backend/docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["backend/docker-entrypoint.sh"]

# SettlePay ops platform — console + pipeline in one container (Cloud Run).
# Build context = the outreach/ project dir. Secrets NEVER enter the image
# (.dockerignore excludes .env); Cloud Run injects them from Secret Manager.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

# deps first (layer-cached until pyproject changes). Derived from pyproject so
# there is one source of truth; the package itself runs from /app source (a
# site-packages install would break PROJECT_ROOT's prompts/migrations paths).
COPY pyproject.toml ./
RUN python -c "import tomllib; d = tomllib.load(open('pyproject.toml','rb'))['project']; \
print('\n'.join(d['dependencies'] + d['optional-dependencies']['web']))" > /tmp/requirements.txt \
    && pip install --no-cache-dir -r /tmp/requirements.txt

# the app: package + playbook + migrations + timing config (paths mirror the
# repo layout because config.PROJECT_ROOT resolves relative to the package)
COPY outreach/ ./outreach/
COPY prompts/ ./prompts/
COPY migrations/ ./migrations/
COPY sequence_config.json ./

RUN useradd --create-home app && chown -R app:app /app
USER app

# shell form so $PORT expands (Cloud Run sets it)
CMD exec python -m uvicorn outreach.web:app --host 0.0.0.0 --port $PORT

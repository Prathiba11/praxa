# syntax=docker/dockerfile:1
#
# Career Copilot container.
#
# Four decisions worth explaining:
#
# 0. It serves the React app. Until a code review it did not: this file
#    still built and launched the earlier Streamlit interface, because all
#    the work went into replacing that interface and nobody opened the
#    Dockerfile. Anyone who ran the container saw the previous version's
#    application. The Node stage below builds `frontend/`, the runtime stage
#    copies the bundle in, and uvicorn serves it on one port alongside /api.
#
# 1. Multi-stage. Dependencies are built in a stage that carries a compiler
#    toolchain; the runtime stage gets only the installed virtualenv. The final
#    image has no build tools in it, which is both smaller and less to attack.
#
#    Dependencies come from pyproject.toml, which is the single list. To keep
#    them in their own cached layer they are installed against a stub package
#    first, so an ordinary source edit does not reinstall chromadb and
#    sentence-transformers. Without the stub, `pip install .` needs the real
#    source and every edit invalidates the layer.
#
# 2. CPU-only torch. `sentence-transformers` pulls in `torch`, and the default
#    PyPI wheel bundles the CUDA runtime - roughly 2.5 GB installed. This
#    container has no GPU and never will, so it installs from PyTorch's CPU
#    index first and lets the dependency resolver find it already satisfied. It
#    is a few hundred megabytes instead, which is a faster build, a smaller
#    image, and several gigabytes less to have opinions about.
#
# 3. PREFETCH_MODELS. The embedder and cross-encoder are ~600 MB and are
#    normally downloaded on first use - a 5-minute pause the first time anyone
#    asks a question. Building with --build-arg PREFETCH_MODELS=true bakes them
#    into the image instead. CI leaves it false so that a Dockerfile mistake is
#    caught in two minutes rather than fifteen; a real deployment sets it true.

# ------------------------------------------------------------- frontend stage
# Node is needed to BUILD the client and not to run it: the output is static
# files, which FastAPI serves. So this whole stage is discarded and none of
# node, npm or node_modules reaches the final image.
FROM node:22-slim AS frontend

WORKDIR /build

# The manifest first, so `npm ci` is cached until a dependency actually changes.
COPY frontend/package.json frontend/package-lock.json ./
# `ci` rather than `install`: it installs exactly the lockfile and fails if the
# lock and package.json have drifted, which is what you want on a clean machine.
RUN npm ci

COPY frontend/ ./
# `npm run build` is `tsc -b && vite build`, so a type error fails the image
# build rather than shipping a broken bundle.
RUN npm run build

# ---------------------------------------------------------------- build stage
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv "$VIRTUAL_ENV"

# CPU-only torch, before anything can pull the CUDA build in as a dependency.
# Its own layer so a change to the dependency list does not redownload it.
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu

# Dependencies second, against a stub package: this layer is cached until
# pyproject.toml changes, so ordinary source edits do not trigger a reinstall.
COPY pyproject.toml README.md ./
RUN mkdir -p career_copilot \
    && touch career_copilot/__init__.py career_copilot/py.typed \
    && pip install . \
    && pip uninstall --yes career-copilot \
    && rm -rf career_copilot

# Now the real source, installed without touching the dependency layer above.
COPY career_copilot ./career_copilot
RUN pip install --no-deps .

# -------------------------------------------------------------- runtime stage
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    HF_HOME=/home/copilot/.cache/huggingface

# Non-root. The app writes only to /app/data, which is owned by this user.
RUN useradd --create-home --uid 10001 copilot

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=copilot:copilot career_copilot ./career_copilot
COPY --chown=copilot:copilot scripts ./scripts
COPY --chown=copilot:copilot kb ./kb

# The built client. `api.app.FRONTEND_DIST` is `<repo root>/frontend/dist`,
# resolved from the package's own location - so with the package at
# /app/career_copilot, this is the path it looks in. Get it wrong and the app
# starts, logs "no frontend bundle at ...", and serves a bare API.
COPY --from=frontend --chown=copilot:copilot /build/dist ./frontend/dist

# The vector index and the SQLite database live here. Mount a volume over it to
# keep them across container replacements; personal CVs are never baked in.
#
# `data/kb/resumes` is created empty rather than just `data`: `repo_root()`
# locates the project by walking up until it finds that path, so without it the
# container starts fine and then fails the first time anyone tailors a CV.
# Mount your own CVs into it, or copy them in at deploy time. With it empty,
# the committed sample CVs under kb/resumes_sample are used instead.
RUN mkdir -p /app/data/kb/resumes && chown -R copilot:copilot /app/data
VOLUME ["/app/data"]

USER copilot

# Optional: bake the models in so first use is not a 5-minute download.
ARG PREFETCH_MODELS=false
RUN if [ "$PREFETCH_MODELS" = "true" ]; then \
        python -c "\
from sentence_transformers import CrossEncoder, SentenceTransformer;\
SentenceTransformer('intfloat/multilingual-e5-base');\
CrossEncoder('cross-encoder/mmarco-mMiniLMv2-L12-H384-v1')" ; \
    fi

EXPOSE 8000

# Against /api/health, which is this application's own readiness answer, rather
# than against / - the single-page mount returns index.html for almost any path
# it does not recognise, so a check on / would pass even with the API broken.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/health', timeout=4).status == 200 else 1)"

# `--factory` because `create_app` is a function, not a module-level app. One
# worker: the retrieval models are several hundred megabytes of resident memory
# each and a second worker would load its own copy.
CMD ["uvicorn", "career_copilot.api.app:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8000"]

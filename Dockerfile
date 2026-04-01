# Build the frontend assets that will be served with the backend image.
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

COPY frontend/package.json ./
COPY frontend/package-lock.json ./
RUN npm install

COPY frontend/ ./

RUN npm run build

# Build the Python backend on top of the LangGraph API base image.
FROM docker.io/langchain/langgraph-api:3.12

# Install UV.
RUN apt-get update && apt-get install -y curl && \
    curl -LsSf https://astral.sh/uv/install.sh | sh && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
ENV PATH="/root/.local/bin:$PATH"

# Copy the compiled frontend where `shared.app` expects it.
COPY --from=frontend-builder /app/frontend/dist /deps/frontend/dist

ADD backend/ /deps/backend

# Install backend dependencies.
RUN uv pip install --system pip setuptools wheel
RUN cd /deps/backend && \
    PYTHONDONTWRITEBYTECODE=1 UV_SYSTEM_PYTHON=1 uv pip install --system -c /api/constraints.txt -e .
ENV LANGGRAPH_HTTP='{"app": "/deps/backend/src/shared/app.py:app"}'
ENV LANGSERVE_GRAPHS='{"agent": "/deps/backend/src/case_generator/graph.py:graph"}'

# Reinstall `/api` so the base runtime keeps the package layout it expects.
RUN mkdir -p /api/langgraph_api /api/langgraph_runtime /api/langgraph_license /api/langgraph_storage && \
    touch /api/langgraph_api/__init__.py /api/langgraph_runtime/__init__.py /api/langgraph_license/__init__.py /api/langgraph_storage/__init__.py
RUN PYTHONDONTWRITEBYTECODE=1 pip install --no-cache-dir --no-deps -e /api

# Remove pip tooling from the final image while keeping UV available.
RUN uv pip uninstall --system pip setuptools wheel && \
    rm -rf /usr/local/lib/python*/site-packages/pip* /usr/local/lib/python*/site-packages/setuptools* /usr/local/lib/python*/site-packages/wheel* && \
    find /usr/local/bin -name "pip*" -delete

WORKDIR /deps/backend

# Kisht app image (the agent, guard, ledger, chat CLI and the voice bridge).
# The model server runs outside this image: on a Mac, mlx_lm.server uses the Apple GPU, which
# containers cannot reach, so the container talks to it at host.docker.internal:8080.
# Stage 1: build the React + TypeScript dashboard.
FROM node:22-slim AS dashboard
WORKDIR /d
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci
COPY dashboard/ ./
RUN npm run build

# Stage 2: the Python app, serving the built dashboard.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev
COPY config.docker.yaml ./config.docker.yaml
COPY lenders ./lenders
COPY knowledge ./knowledge
COPY compliance ./compliance
COPY tools/make_loan_book.py ./tools/make_loan_book.py
COPY results/evals ./results/evals
COPY --from=dashboard /d/dist ./dashboard/dist
COPY docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x docker-entrypoint.sh
EXPOSE 5050 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["bridge", "--host", "0.0.0.0", "--port", "5050"]

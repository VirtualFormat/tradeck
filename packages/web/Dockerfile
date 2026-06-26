# Multi-arch official image (amd64 + arm64). Used for container-only dev.
FROM node:24-bookworm-slim AS base
ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH
RUN corepack enable
WORKDIR /app

# --- dev target: source bind-mounted, node_modules in a container volume,
# deps installed at runtime via `docker compose exec`. Vite dev server. ---
FROM base AS dev
EXPOSE 5173
CMD ["sh", "-c", "pnpm -F @tradeck/web dev"]

# --- build target (for future static production image) ---
FROM base AS build
COPY . .
RUN pnpm install --frozen-lockfile && pnpm -F @tradeck/web build

# --- prod: serve static assets via nginx (multi-arch) ---
FROM nginx:1.27-bookworm AS prod
COPY --from=build /app/packages/web/dist /usr/share/nginx/html
EXPOSE 80

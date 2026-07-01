# Multi-arch official image (amd64 + arm64). Used for container-only dev.
FROM node:24-bookworm-slim AS base
ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH
RUN corepack enable
WORKDIR /app

# --- dev target: source bind-mounted, node_modules in a container volume,
# deps installed at runtime via `docker compose exec`. Container stays alive
# (does NOT auto-run vite) so deps can be installed first; start the dev
# server manually afterwards. Matches Dev Container `overrideCommand`. ---
FROM base AS dev
EXPOSE 5173
CMD ["sleep", "infinity"]

# --- build target (for future static production image) ---
FROM base AS build
ARG VITE_API_BASE_URL=http://localhost:3000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
COPY . .
RUN pnpm install --frozen-lockfile && pnpm -F @tradeck/web build

# --- prod: serve static assets via nginx (multi-arch) ---
FROM nginx:1.27-bookworm AS prod
COPY --from=build /app/packages/web/dist /usr/share/nginx/html
EXPOSE 80

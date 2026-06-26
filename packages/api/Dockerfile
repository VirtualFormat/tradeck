# Multi-arch official image (amd64 + arm64). Used for container-only dev.
FROM node:24-bookworm-slim AS base
ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH
RUN corepack enable
WORKDIR /app

# --- dev target: source is bind-mounted, node_modules lives in a container
# volume. Dependencies are installed at runtime via `docker compose exec`.
# The container stays alive (does NOT auto-run the dev server) so it can be
# exec'd into to `pnpm install` first; start the watcher manually afterwards.
# This also matches the Dev Container `overrideCommand` behavior. ---
FROM base AS dev
EXPOSE 3000
CMD ["sleep", "infinity"]

# --- build target (for future production image) ---
FROM base AS build
COPY . .
RUN pnpm install --frozen-lockfile && pnpm -F @tradeck/api build

FROM base AS prod
COPY --from=build /app/packages/api/dist ./dist
EXPOSE 3000
CMD ["node", "dist/main.js"]

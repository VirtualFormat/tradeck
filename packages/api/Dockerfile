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

# --- build target ---
FROM base AS build
COPY . .
RUN pnpm install --frozen-lockfile \
  && pnpm -F @tradeck/shared build \
  && pnpm -F @tradeck/api build

FROM base AS prod
ENV NODE_ENV=production
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/packages/api/package.json ./packages/api/package.json
COPY --from=build /app/packages/api/dist ./packages/api/dist
COPY --from=build /app/packages/shared ./packages/shared
EXPOSE 3000
CMD ["node", "packages/api/dist/main.js"]

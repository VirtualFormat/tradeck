# Multi-arch official image (amd64 + arm64). Used for container-only dev.
FROM node:24-bookworm-slim AS base
ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH
RUN corepack enable
WORKDIR /app

# --- dev target: source is bind-mounted, node_modules lives in a container
# volume. Dependencies are installed at runtime via `docker compose exec`. ---
FROM base AS dev
EXPOSE 3000
CMD ["sh", "-c", "pnpm -F @tradeck/api dev"]

# --- build target (for future production image) ---
FROM base AS build
COPY . .
RUN pnpm install --frozen-lockfile && pnpm -F @tradeck/api build

FROM base AS prod
COPY --from=build /app/packages/api/dist ./dist
EXPOSE 3000
CMD ["node", "dist/main.js"]

# Repository Guidelines

## Project Structure & Module Organization

Tradeck is a pnpm workspace for an internal real-time market dashboard:

- `packages/web`: React 18 + Vite frontend. UI, dashboard components, chart hooks, API hooks, and Zustand stores are in `src/`.
- `packages/api`: NestJS modular monolith. Domain modules are in `src/modules/`; infrastructure adapters for config, PostgreSQL/Drizzle, and Redis are in `src/infra/`.
- `packages/shared`: shared TypeScript models, constants, and Zod schemas exported as `@tradeck/shared`.
- `docs/`: architecture notes. Read `docs/ARCHITECTURE.md` before changing module boundaries.

Root files include `pnpm-workspace.yaml`, `docker-compose.yml`, and `.env.example`.

## Build, Test, and Development Commands

Use Node `>=24 <25` and pnpm `9.15.0`.

- `pnpm install`: install workspace dependencies.
- `pnpm dev:api`: run the NestJS API in watch mode.
- `pnpm dev:web`: run the Vite frontend locally.
- `pnpm build`: build all workspace packages.
- `pnpm typecheck`: run TypeScript checks across packages.
- `docker compose up -d --build`: start the production-style local deployment.
- `docker compose -f .devcontainer/docker-compose.yml up -d --build`: start the devcontainer stack.
- `docker compose -f .devcontainer/docker-compose.yml exec api pnpm typecheck`: build shared types, then run checks inside the devcontainer.

Do not install Node dependencies on the host. Use the devcontainer for `pnpm install`, checks, and dev servers. The root `lint` script delegates to package lint scripts, but package lint scripts are not defined yet.

## Coding Style & Naming Conventions

Write TypeScript with strict compiler settings enabled by `tsconfig.base.json`. Use 2-space indentation, semicolons, single quotes, and trailing commas where the existing code uses them. Prefer named exports for shared models and utilities.

Frontend components use `PascalCase` filenames, for example `DashboardHeader.tsx`. Hooks use `useX.ts`; API hooks live in `packages/web/src/api/`; realtime state belongs in `packages/web/src/stores/`.

Backend classes follow NestJS conventions: `*.module.ts`, `*.controller.ts`, `*.service.ts`, and connector implementations under `packages/api/src/modules/connectors/`.

## Testing Guidelines

No test framework or test scripts are currently configured. For now, run `pnpm typecheck` and relevant builds before submitting changes. When adding tests, colocate them near the subject code with names such as `candle-aggregator.spec.ts` or `DataSourceForm.test.tsx`, and add package scripts so `pnpm -r test` can run them.

## Commit & Pull Request Guidelines

Recent commits use Conventional Commit-style prefixes such as `feat(web): ...`, `style(web): ...`, and `feat: ...`. Keep commit subjects imperative and scoped when useful.

Pull requests should include a summary, affected packages, commands run, and screenshots or recordings for UI changes. Link related issues when available. Call out environment or schema changes, especially updates to `.env.example`, Docker Compose, Drizzle schema, Redis usage, or connector behavior.

## Architecture Notes

Keep the data ownership split: TanStack Query handles fetched REST/snapshot data, while Zustand handles pushed realtime data. Connectors should normalize and emit shared models only; ingestion owns persistence, Redis snapshots, and realtime fan-out.

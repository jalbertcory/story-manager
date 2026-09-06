# Frontend

The frontend is a React and Vite app for the Story Manager web UI.

## Commands

```bash
npm ci
npm run dev
npm run lint
npm run typecheck
npm test -- --run
npm run test:e2e
```

During local development, Vite runs on `http://localhost:5173` and proxies `/api` requests to the backend on `http://localhost:8000`.

## Static checks

Production TypeScript uses strict mode, `noUncheckedIndexedAccess`, and
`exactOptionalPropertyTypes`. Check array and dictionary lookups before using
values, and omit optional API fields when no value is available.

ESLint uses the TypeScript project for its recommended type-aware rules, including
unsafe `any` propagation, floating promises, and async callbacks passed where a
synchronous callback is expected. Handle failures in async UI actions. Background
React Query refreshes use explicit `void`; query errors remain in query state.

Tests receive ordinary lint checks outside the production TypeScript project.
The compile-only API contract fixture contains deliberate type errors verified by
`tsc`, so it is excluded from type-aware lint. Generated API declarations are not
linted; `npm run api:check` verifies they match the backend schema.

Run `make pr-check` from the repository root before opening or updating a PR.
This includes clean-install validation, lint, both type checkers, API schema drift,
and dependency audits. The frontend build also runs TypeScript first.

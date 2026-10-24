# web

The Next.js dashboard for OnePublish. See the [root README](../README.md).

- `src/app/api/[...path]/route.ts` forwards `/api/*` to the FastAPI service (`API_INTERNAL_URL`).
- `src/lib/api/schema.d.ts` is generated from the API's OpenAPI spec with `pnpm gen:api`; don't edit it by hand.
- Every page is a client component that loads data through `src/lib/api/hooks.ts` (TanStack Query).

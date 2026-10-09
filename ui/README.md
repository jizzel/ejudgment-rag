# E-Judgment research UI

Local Next.js 16 UI over the FastAPI service: search, source-grounded answers and a passage viewer, with GhaLII attribution on every page. No sign-in yet (M4 slice 2), so run it locally only.

```bash
npm install
EJUDGMENT_API_URL=http://127.0.0.1:8000 npm run dev    # the API: poetry run uvicorn ejudgment.api.main:app
npm run lint && npm run typecheck && npm test && npm run build
```

- `npm run dev` and `npm start` listen on `127.0.0.1` only (Next defaults to `0.0.0.0`); a test keeps it that way until sign-in exists (M4 slice 2).
- Invalid filters in a URL or the Ask form (e.g. `year_to=20x5`) are shown as errors, never dropped, so a search is never silently widened. An over-long query is rejected, not cut.
- All API calls run server-side (server components and `src/app/api/chat/route.ts`), so the browser never sees the API address and no CORS is needed.
- `src/lib/api-types.ts` is generated from the API's OpenAPI snapshot `src/lib/openapi.json`. After an API change: `poetry run python -m ejudgment.api.export_openapi && npm run gen:api` (a pytest and a vitest fail while either is stale).
- Corpus text is untrusted: it is rendered only as React text (no `dangerouslySetInnerHTML`). Highlighting splits strings into `<mark>` nodes.
- Pages show a PDF page only when the API marks it verified.
- `AGENTS.md` in this folder is written by `next dev`, and points to the Next docs bundled in `node_modules/next/dist/docs/`.

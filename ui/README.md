# E-Judgment research UI

Next.js 16 UI over the FastAPI service: search, source-grounded answers and a passage viewer, with GhaLII attribution on every page. Users sign in with an invited account (`poetry run python -m ejudgment.worker.users create …`). Until the TLS deployment (M4 slice 3), run it locally only.

```bash
npm install
UI_INSECURE_COOKIES=1 EJUDGMENT_API_URL=http://127.0.0.1:8000 npm run dev    # the API: poetry run uvicorn ejudgment.api.main:app
npm run lint && npm run typecheck && npm test && npm run build
```

- `npm run dev` and `npm start` listen on `127.0.0.1` only (Next defaults to `0.0.0.0`); a test keeps it that way until the TLS deployment (M4 slice 3).
- Sign-in: the session token lives in an `HttpOnly`, `SameSite=Lax` cookie, `Secure` unless `UI_INSECURE_COOKIES=1` (needed on plain http). Server code sends it to the API as a bearer token, and a 401 returns the user to `/login`. `src/proxy.ts` only redirects visitors without a cookie; the chat route also refuses foreign `Origin`s.
- Invalid filters in a URL or the Ask form (e.g. `year_to=20x5`) are shown as errors, never dropped, so a search is never silently widened. An over-long query is rejected, not cut.
- All API calls run server-side (server components and `src/app/api/chat/route.ts`), so the browser never sees the API address and no CORS is needed.
- `src/lib/api-types.ts` is generated from the API's OpenAPI snapshot `src/lib/openapi.json`. After an API change: `poetry run python -m ejudgment.api.export_openapi && npm run gen:api` (a pytest and a vitest fail while either is stale).
- Corpus text is untrusted: it is rendered only as React text (no `dangerouslySetInnerHTML`). Highlighting splits strings into `<mark>` nodes.
- Pages show a PDF page only when the API marks it verified.
- `/review` (reviewers and admins; the nav link is hidden for others, the API enforces it): gold-question list and editor. Writes go through server actions (`src/app/review/actions.ts`) with the version the page was loaded at; `src/lib/review.ts` mirrors the API's approval rule so Approve is disabled until it holds.
- `AGENTS.md` in this folder is written by `next dev`, and points to the Next docs bundled in `node_modules/next/dist/docs/`.

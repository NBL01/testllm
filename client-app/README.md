# Client App (Next.js)

Thin client-facing MVP for the evaluation job workflow.

## Scope

This app is intentionally narrow:

1. create an evaluation job
2. run the evaluation
3. view job status and summary metrics
4. inspect failed cases
5. inspect oracle traces
6. copy/export a simple report

All evaluation logic stays in FastAPI.

## Run

From `client-app`:

```bash
npm install
npm run dev
```

Set API base URL if needed:

```bash
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000 npm run dev
```

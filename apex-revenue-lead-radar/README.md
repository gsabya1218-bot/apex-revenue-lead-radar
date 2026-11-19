# Apex Revenue Lead Radar — MVP

A small FastAPI service for storing and reviewing evidence-backed commercial leads.

## Scope
- Geography: USA and continental Europe, including Ireland.
- Exclude: India and the UK.
- Do not qualify job postings, hiring, or generic data-partnership roles as buyer demand.
- Keep leads in `needs_review` until a human validates the evidence.

## Deploy to Render
1. Upload the extracted repository files to your GitHub repository (keep the folder structure).
2. In Render, choose **New + → Blueprint** and select the repository. Render reads `render.yaml`.
3. In the service environment settings, add `DATABASE_URL` using the Supabase Postgres connection string. Use the Supabase connection string directly in Render; do not paste it into chat.
4. Deploy. Check `/health`; it should report `status: ok` and `database: connected`.
5. Open `/docs` to test the API.

## Supabase schema
Run `sql/schema.sql` in Supabase **SQL Editor** once before using the app.

## API
- `GET /` service information
- `GET /health` app + database health
- `GET /agents` 30-agent MVP configuration
- `GET /leads?limit=50&offset=0` list leads
- `POST /leads` add/update a lead; requires `X-API-Key` header

## Security
- Keep `DATABASE_URL` and `API_KEY` in Render environment variables only.
- Never commit `.env` or share credentials in chat.
- The 30 agent entries are configuration placeholders, not autonomous live agents. Connectors, source-specific collection, evidence checks, scheduling, and human approval workflows still need to be implemented before this is a production lead-generation system.

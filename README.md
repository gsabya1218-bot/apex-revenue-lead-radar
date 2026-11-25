# Apex Revenue Lead Radar

Apex Metrics' public-web commercial intelligence discovery service. The existing FastAPI/Postgres API remains in place; this update adds a seven-day discovery job for public LinkedIn project posts, public LinkedIn job listings and broader market-data/consulting signals.

## New discovery coverage
- LinkedIn posts: public, indexed requests for consultants, research partners, market sizing, CAGR, consumer insights, external data, competitive intelligence and defined project scopes.
- LinkedIn jobs: publicly indexed roles such as Head/Director of Data, Consumer Insights, Market Research, Market Intelligence and Analytics, with descriptions that mention market-data needs.
- Wider commercial triggers: data gaps tied to pricing, margin, market entry, launches, category growth, supply-chain or competitive decisions.
- Geography: USA and continental Europe, including Ireland. UK and India are excluded.
- Recency: strict rolling seven-day evidence window.

## Evidence and qualification
The discovery script only creates candidates. A public post or job vacancy is not proof of a buyer or budget. Before any candidate is promoted to P1/P2, validate:
1. A specific, dated, checkable fact and original source URL.
2. The actual decision and deadline owned by the relevant executive.
3. One external-data blind spot Apex can investigate.
4. At least three independent evidence signals, a verified company, named decision owner and credible outreach route.
5. A realistic Apex deliverable and paid-project fit.

P1 is reserved for explicit project requirements with a clear timeline and multiple recent evidence signals. P2 requires multiple recent signals and an actionable data/insights need. Generic hiring and general company news remain hypotheses.

## LinkedIn access policy
The connector searches only public search-index RSS results for LinkedIn URLs. It does not log in, bypass access controls, scrape private posts, collect private member data, or automate LinkedIn messaging. Coverage is incomplete because search engines do not index every post or job.

## Run locally
```bash
pip install -r requirements.txt
python app/discovery.py
```
If `DATABASE_URL` is configured, candidates are written to the existing Postgres `leads` table. Without it, the scan still runs and writes local output files:
- `output/discovery_candidates.json`
- `output/discovery_candidates.csv`

The API remains `uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}`.

## Scheduled scan
`.github/workflows/december-lead-radar.yml` runs at 08:00 IST and only performs scheduled scans from December 1–5. A manual workflow dispatch is available for testing. Results are uploaded as GitHub Actions artifacts for 14 days. No paid search provider, paid database, custom domain or additional infrastructure is configured by this update.

## Deployment and limitations
The Render blueprint and Dockerfile continue to use the existing FastAPI app. A commit to the deployment branch is required for Render to rebuild; a feature branch does not by itself confirm deployment. The existing Postgres connection must be healthy for candidates to appear in the API's `/leads` endpoint. GitHub Actions artifact-only mode works without a database, but does not make results persistent in the hosted API.

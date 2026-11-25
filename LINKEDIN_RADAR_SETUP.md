# LinkedIn Buyer-Signal Radar — Setup and Operating Notes

## Purpose
Find public LinkedIn signals posted within the last seven days that may indicate:
1. A private-sector consulting / market-research / consumer-insights project with a stated scope or timeline.
2. A company hiring a senior Data, Analytics, Consumer Insights, Market Intelligence or Strategy leader, where the job description explicitly names market data, CAGR, consumer panels, syndicated data, competitive intelligence or external research needs.

This is a discovery queue, not a buyer-intent oracle. Hiring alone is never classified as active vendor procurement. All candidates require human verification.

## Search access
The collector searches public search-engine indexes for public LinkedIn URLs. It does not log into LinkedIn, scrape authenticated pages, bypass rate limits, or collect private profile data.

Configure one search provider in GitHub Actions repository secrets:
- `SERPER_API_KEY`; OR
- `GOOGLE_CSE_API_KEY` and `GOOGLE_CSE_ID`.

The code does not create or purchase these credentials. Check the provider's current pricing and quota before adding a key. No paid service should be enabled without Apex approval.

LinkedIn's official APIs do not provide unrestricted search over all posts and jobs. Use approved LinkedIn API access or public indexed pages only. Search snippets may be incomplete and dates may be absent; undated items are discarded.

## Campaign controls
- Rolling freshness window: 7 days.
- Territory: USA and continental Europe, including Ireland.
- Excluded: UK and India.
- December closure window: Dec 1–5, 2026.
- Scheduled workflow: 08:00 IST daily, date-gated to Dec 1–5.
- Manual workflow dispatch is available for testing, but does not authorize outreach.

## Signal treatment
- `consulting_project_brief`: public post appears to request a consultant, research partner or project. A stated timeline increases priority, but the record remains a candidate until buyer, budget route and data gap are verified.
- `data_insights_hiring_signal`: job post indicates a data/insights capability requirement. Hiring is P3 by default; upgrade only if the role description explicitly identifies a time-bound external data/vendor/research dependency and the buyer route is verified.
- `P1` is never auto-assigned. It requires direct buyer validation, explicit external data requirement, accountable owner, deadline and a realistic paid path.

## Output
The run creates dated JSON and CSV files under `artifacts/` and uploads them as a GitHub Actions artifact. If `DATABASE_URL` is configured, it also writes to `linkedin_signal_candidates`. A database failure does not discard the local export.

## Required manual validation before any outreach
For every shortlisted company:
1. Open the original public LinkedIn post/job page and confirm it is still live.
2. Verify company identity, country, ownership and current posting date.
3. Capture exact project scope, variables, geography, sample/coverage, deliverable, start date, deadline and duration.
4. Verify the named hiring/project owner from an attributable company or professional source.
5. Confirm whether the requirement needs external data or research; separate fact from hypothesis.
6. Establish the economic buyer, lawful contact route, budget/procurement path and decision window.
7. Apply Apex's validation formula: specific checkable fact + decision/deadline owned by the executive + one unknown the company needs to resolve.
8. Keep hiring-only signals at P3 unless stronger independent evidence is found.

No messages are sent, no forms are submitted and no outreach is performed by this workflow.

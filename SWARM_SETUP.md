# Apex Executive Intelligence Swarm — Setup

The GitHub Actions worker runs 12 specialist model calls per candidate. Each specialist receives the case file plus prior agent handoffs. Handoffs, tasks, extracted evidence and audit records are persisted in Supabase/Postgres. Public-source search uses Tavily; analysis uses an OpenAI-compatible Chat Completions endpoint.

The swarm prepares internal research and outreach drafts only. It never sends email/LinkedIn messages, submits forms, spends money, contacts prospects or commits delivery terms.

## Required GitHub Actions secrets
Add these under Repository Settings → Secrets and variables → Actions:
- DATABASE_URL — existing Supabase Postgres connection string.
- OPENAI_API_KEY — model provider API key.
- TAVILY_API_KEY — public web search API key.

Optional repository variables: OPENAI_MODEL (default gpt-4.1-mini), OPENAI_BASE_URL (default https://api.openai.com/v1/chat/completions), SWARM_MAX_CANDIDATES (default 5).

Never put keys in source files, commits, logs or chat. The worker creates agent_runs, agent_tasks, agent_handoffs, lead_evidence and agent_audit tables idempotently.

Agent P1 recommendations are stored as P2 pending human review. Agent-extracted evidence is not independently verified. Review source URLs before outreach. No result promises a buyer, meeting or conversion.

## Department-level ethical commercial red team
The current runtime contains 20 sequential specialist roles. In addition to the original research and conversion roles, it reviews sales/revenue, marketing/customer intelligence, finance/pricing, operations/supply chain, product/innovation, strategy/corporate development, and organization/execution. An ethical commercial red-team role stress-tests the hypotheses and records falsifiers and counter-evidence.

This is business-intelligence adversarial analysis, not cybersecurity penetration testing. It does not scan company systems, probe infrastructure, access accounts, use deception, target individual employees, seek confidential information, or bypass controls. All analysis must be grounded in lawful public sources. A pain hypothesis is not a confirmed internal problem or buying intent.

The Quality & Evidence Auditor records the department pain map, CEO brief, unknowns, counter-evidence and outreach draft in the agent audit record. A P1 model recommendation remains P2 pending human source verification.

"""Public LinkedIn signal discovery for Apex Metrics.

Uses a search API to discover publicly indexed LinkedIn posts and job pages.
Does NOT log into LinkedIn, scrape authenticated pages, bypass controls, or infer
purchase intent from hiring alone. All records remain candidates until reviewed.
"""
from __future__ import annotations

import csv
import json
import logging
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

LOG = logging.getLogger("apex-linkedin-radar")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(message)s")

WINDOW_DAYS = int(os.getenv("LINKEDIN_WINDOW_DAYS", "7"))
CAMPAIGN_START = date.fromisoformat(os.getenv("CAMPAIGN_START", "2026-12-01"))
CAMPAIGN_END = date.fromisoformat(os.getenv("CAMPAIGN_END", "2026-12-05"))
TODAY = datetime.now(timezone.utc).date()

# UK and India are intentionally absent. Ireland is included.
REGIONS = [
    ("United States", "US"), ("Ireland", "IE"), ("Germany", "DE"),
    ("France", "FR"), ("Netherlands", "NL"), ("Belgium", "BE"),
    ("Switzerland", "CH"), ("Italy", "IT"), ("Spain", "ES"),
    ("Sweden", "SE"), ("Denmark", "DK"), ("Norway", "NO"),
    ("Finland", "FI"), ("Austria", "AT"), ("Portugal", "PT"),
]

PROJECT_QUERIES = [
    'site:linkedin.com/posts ("looking for" OR "seeking") ("market research" OR "consumer insights" OR "market intelligence" OR "CAGR") (consultant OR consulting OR project)',
    'site:linkedin.com/posts ("project brief" OR "consulting project" OR "independent consultant") ("data" OR "insights" OR "market sizing" OR "competitive intelligence")',
    'site:linkedin.com/posts ("need support" OR "seeking support" OR "request for proposal") ("consumer research" OR "market data" OR "pricing" OR "market entry")',
]
HIRING_QUERIES = [
    'site:linkedin.com/jobs/view ("Head of Insights" OR "Director Consumer Insights" OR "Market Intelligence" OR "Head of Data Analytics")',
    'site:linkedin.com/jobs/view ("CAGR" OR "syndicated data" OR "market data" OR "consumer panel" OR "external data") (insights OR analytics OR strategy)',
    'site:linkedin.com/jobs/view ("competitive intelligence" OR "market research" OR "consumer data" OR "category insights") (director OR head OR lead OR manager)',
]

PROJECT_TERMS = re.compile(
    r"\b(consulting project|project brief|independent consultant|seeking a consultant|"
    r"looking for a consultant|market research|consumer insights|market intelligence|"
    r"competitive intelligence|market sizing|CAGR|pricing research|market entry|"
    r"customer segmentation|consumer research|external data|syndicated data)\b", re.I)
BUYER_INTENT_TERMS = re.compile(
    r"\b(seeking|looking for|need support|project brief|request for|engage a|"
    r"appoint a|external partner|consultant|vendor evaluation|supplier search)\b", re.I)
DATA_TERMS = re.compile(
    r"\b(CAGR|market data|consumer data|consumer insights|market research|"
    r"market intelligence|competitive intelligence|syndicated data|pricing data|"
    r"category data|retail data|panel data|customer analytics|data analytics|"
    r"market sizing|forecasting|share of market|share of voice)\b", re.I)
LEADER_TERMS = re.compile(
    r"\b(head of (data|insights|analytics|market intelligence|consumer insights)|"
    r"chief data officer|chief analytics officer|director of (data|insights|analytics)|"
    r"VP (of )?(data|insights|analytics)|market intelligence lead|consumer insights lead)\b", re.I)
TIMELINE = re.compile(
    r"\b(by\s+(?:\d{1,2}[ /-]\w+[ /-]?\d{0,4}|\w+\s+\d{1,2}|\d{1,2}\s+\w+)|"
    r"deadline\s*:?\s*[^.;,]{3,45}|start(?:ing)?\s+(?:on|by|in)\s+[^.;,]{3,35}|"
    r"within\s+\d+\s+(?:days?|weeks?|months?)|\d+[- ]week(?:s)?|"
    r"immediate(?:ly)?|urgent|asap|Q[1-4]\s*20\d{2})\b", re.I)
COMPANY_AT = re.compile(r"\b(?:at|@)\s+([A-Z][A-Za-z0-9&.,' -]{1,65}?)(?:\s*[|•,-]|$)", re.I)
DATE_PATTERNS = [
    re.compile(r"\b(?:Nov|November|Dec|December)\s+\d{1,2},?\s+2026\b", re.I),
    re.compile(r"\b\d{1,2}\s+(?:Nov|November|Dec|December)\s+2026\b", re.I),
]

def http_json(url: str, headers: dict[str, str], body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8", "replace"))

def search_serper(query: str) -> list[dict]:
    key = os.getenv("SERPER_API_KEY")
    if not key:
        return []
    payload = {"q": query, "num": 10, "tbs": "qdr:w"}
    result = http_json("https://google.serper.dev/search",
                       {"X-API-KEY": key, "Content-Type": "application/json"}, payload)
    return result.get("organic", [])

def search_google_cse(query: str) -> list[dict]:
    key, cx = os.getenv("GOOGLE_CSE_API_KEY"), os.getenv("GOOGLE_CSE_ID")
    if not (key and cx):
        return []
    params = urllib.parse.urlencode({"key": key, "cx": cx, "q": query,
                                     "dateRestrict": "d7", "num": 10})
    result = http_json("https://www.googleapis.com/customsearch/v1?" + params,
                       {"User-Agent": "ApexMetricsPublicResearch/1.0"})
    rows = []
    for item in result.get("items", []):
        meta = item.get("pagemap", {}).get("metatags", [{}])[0]
        rows.append({"title": item.get("title", ""), "link": item.get("link", ""),
                     "snippet": item.get("snippet", ""),
                     "date": meta.get("article:published_time") or meta.get("date") or ""})
    return rows

def search(query: str) -> list[dict]:
    if os.getenv("SERPER_API_KEY"):
        return search_serper(query)
    if os.getenv("GOOGLE_CSE_API_KEY") and os.getenv("GOOGLE_CSE_ID"):
        return search_google_cse(query)
    return []

def parse_date(value: str) -> date | None:
    if not value:
        return None
    value = str(value).strip()
    now = datetime.now(timezone.utc).date()
    m = re.search(r"(\d+)\s+(hour|day|week)s?\s+ago", value, re.I)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        return now - timedelta(days=(1 if unit == "hour" else 7 if unit == "week" else n))
    m = re.search(r"yesterday", value, re.I)
    if m:
        return now - timedelta(days=1)
    for pattern in DATE_PATTERNS:
        m = pattern.search(value)
        if m:
            raw = m.group(0).replace(",", "")
            for fmt in ("%b %d %Y", "%B %d %Y", "%d %b %Y", "%d %B %Y"):
                try:
                    return datetime.strptime(raw, fmt).date()
                except ValueError:
                    pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None

def classify(url: str, title: str, snippet: str) -> str:
    text = f"{title} {snippet}".lower()
    if "/jobs/view/" in url:
        return "data_insights_hiring_signal"
    if PROJECT_TERMS.search(text) and BUYER_INTENT_TERMS.search(text):
        return "consulting_project_brief"
    return "linkedin_business_signal"

def company_guess(title: str, snippet: str) -> str | None:
    text = f"{title} | {snippet}"
    m = COMPANY_AT.search(text)
    if m:
        name = re.split(r"\s+(?:is hiring|is looking|seeks|posted|posted a job)", m.group(1), flags=re.I)[0]
        return name.strip(" .,-|")[:100] or None
    # Job result titles often end with " - Company".
    if "/jobs/view/" in text:
        m = re.search(r"\s[-|]\s([A-Z][A-Za-z0-9&.,' -]{1,60})$", title)
        if m:
            return m.group(1).strip()
    return None

def infer_timeline(text: str) -> str | None:
    m = TIMELINE.search(text or "")
    return m.group(0).strip()[:180] if m else None

def evidence_level(kind: str, text: str, timeline: str | None) -> tuple[str, int]:
    # Hiring is not buyer intent. Explicit project posts with timeline are still
    # unvalidated until the company and budget owner are checked.
    if kind == "consulting_project_brief" and BUYER_INTENT_TERMS.search(text) and DATA_TERMS.search(text):
        return ("P2_CANDIDATE_VALIDATE", 65 if timeline else 52)
    if kind == "data_insights_hiring_signal" and DATA_TERMS.search(text):
        return ("P3_HIRING_SIGNAL_ONLY", 35)
    if DATA_TERMS.search(text):
        return ("P3_RESEARCH_SIGNAL", 25)
    return ("REVIEW_OR_REJECT", 10)

def build_queries() -> list[tuple[str, str, str]]:
    jobs = []
    for country, code in REGIONS:
        for q in PROJECT_QUERIES:
            jobs.append((country, "project", f"{q} {country}"))
        for q in HIRING_QUERIES:
            jobs.append((country, "hiring", f"{q} {country}"))
    return jobs

def collect() -> list[dict[str, Any]]:
    if not (os.getenv("SERPER_API_KEY") or
            (os.getenv("GOOGLE_CSE_API_KEY") and os.getenv("GOOGLE_CSE_ID"))):
        LOG.error("No search provider configured. Set SERPER_API_KEY or GOOGLE_CSE_API_KEY + GOOGLE_CSE_ID.")
        return []
    found: dict[str, dict] = {}
    for country, stream, query in build_queries():
        try:
            for row in search(query):
                url = row.get("link") or row.get("url") or ""
                if "linkedin.com/" not in url.lower():
                    continue
                # Keep only public LinkedIn post and job result URLs.
                if not ("/posts/" in url or "/jobs/view/" in url or "/pulse/" in url):
                    continue
                title = row.get("title", "")
                snippet = row.get("snippet", "") or row.get("description", "")
                date_text = row.get("date") or row.get("datePublished") or ""
                published = parse_date(date_text)
                if not published:
                    # Search operators are not a substitute for a verifiable date.
                    continue
                age = (TODAY - published).days
                if age < 0 or age > WINDOW_DAYS:
                    continue
                if re.search(r"\b(United Kingdom|UK|India|Bengaluru|London, UK)\b",
                             f"{title} {snippet}", re.I):
                    continue
                kind = classify(url, title, snippet)
                combined = f"{title}. {snippet}"
                timeline = infer_timeline(combined)
                label, score = evidence_level(kind, combined, timeline)
                key = url.split("?")[0].rstrip("/")
                found[key] = {
                    "company_name": company_guess(title, snippet),
                    "country": country,
                    "signal_type": kind,
                    "title": title[:500],
                    "snippet": snippet[:3000],
                    "source_url": key,
                    "source_name": "LinkedIn public indexed result",
                    "published_date": published.isoformat(),
                    "age_days": age,
                    "timeline_text": timeline,
                    "matched_data_terms": sorted(set(x.lower() for x in DATA_TERMS.findall(combined))),
                    "lead_status": label,
                    "signal_score": score,
                    "specific_checkable_fact": f"Public LinkedIn result dated {published.isoformat()}: {title}",
                    "executive_decision_implication": (
                        "Validate whether this brief or role owns a current market/data decision; "
                        "do not assume a vendor purchase from the post alone."
                    ),
                    "unknown_to_validate": (
                        "Whether external data/research is required, who controls budget, "
                        "the decision deadline, and whether an incumbent provider already covers it."
                    ),
                    "buyer_role": "Hiring manager / Head of Data, Insights, Analytics or Market Intelligence"
                                  if kind == "data_insights_hiring_signal" else "Project sponsor / Strategy or Insights lead",
                    "qualification_note": (
                        "Candidate only. Verify original LinkedIn page, legal entity, geography, "
                        "deadline, buyer, data gap, spend route and Apex fit before outreach."
                    ),
                }
        except Exception as exc:
            LOG.warning("Search failed country=%s stream=%s error=%s",
                        country, stream, type(exc).__name__)
        time.sleep(0.15)
    return sorted(found.values(), key=lambda x: (x["signal_score"], x["published_date"]), reverse=True)

def persist_postgres(rows: list[dict]) -> int:
    dsn = os.getenv("DATABASE_URL")
    if not dsn or not rows:
        return 0
    import psycopg2
    from contextlib import closing
    inserted = 0
    with closing(psycopg2.connect(dsn, sslmode="require", connect_timeout=12)) as conn:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS linkedin_signal_candidates (
                      id BIGSERIAL PRIMARY KEY,
                      company_name TEXT, country TEXT NOT NULL, signal_type TEXT NOT NULL,
                      title TEXT NOT NULL, snippet TEXT, source_url TEXT NOT NULL UNIQUE,
                      source_name TEXT NOT NULL, published_date DATE NOT NULL,
                      age_days INTEGER NOT NULL, timeline_text TEXT, matched_data_terms TEXT[],
                      lead_status TEXT NOT NULL, signal_score INTEGER NOT NULL,
                      specific_checkable_fact TEXT, executive_decision_implication TEXT,
                      unknown_to_validate TEXT, buyer_role TEXT, qualification_note TEXT,
                      raw_payload JSONB, first_seen_at TIMESTAMPTZ DEFAULT NOW(),
                      last_seen_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                for r in rows:
                    cur.execute("""
                      INSERT INTO linkedin_signal_candidates
                      (company_name,country,signal_type,title,snippet,source_url,source_name,
                       published_date,age_days,timeline_text,matched_data_terms,lead_status,
                       signal_score,specific_checkable_fact,executive_decision_implication,
                       unknown_to_validate,buyer_role,qualification_note,raw_payload)
                      VALUES (%(company_name)s,%(country)s,%(signal_type)s,%(title)s,%(snippet)s,
                       %(source_url)s,%(source_name)s,%(published_date)s,%(age_days)s,
                       %(timeline_text)s,%(matched_data_terms)s,%(lead_status)s,%(signal_score)s,
                       %(specific_checkable_fact)s,%(executive_decision_implication)s,
                       %(unknown_to_validate)s,%(buyer_role)s,%(qualification_note)s,%(raw_payload)s)
                      ON CONFLICT (source_url) DO UPDATE SET
                       last_seen_at=NOW(), snippet=EXCLUDED.snippet,
                       lead_status=EXCLUDED.lead_status, signal_score=EXCLUDED.signal_score
                    """, {**r, "raw_payload": json.dumps(r)})
                    inserted += cur.rowcount
    return inserted

def write_outputs(rows: list[dict]) -> None:
    out = Path(os.getenv("OUTPUT_DIR", "artifacts"))
    out.mkdir(parents=True, exist_ok=True)
    stamp = TODAY.isoformat()
    (out / f"linkedin_candidates_{stamp}.json").write_text(
        json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(),
                    "window_days": WINDOW_DAYS, "campaign_start": CAMPAIGN_START.isoformat(),
                    "campaign_end": CAMPAIGN_END.isoformat(),
                    "campaign_actionable_today": CAMPAIGN_START <= TODAY <= CAMPAIGN_END,
                    "count": len(rows), "candidates": rows}, indent=2), encoding="utf-8")
    if rows:
        with (out / f"linkedin_candidates_{stamp}.csv").open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

def main() -> int:
    rows = collect()
    write_outputs(rows)
    try:
        saved = persist_postgres(rows)
    except Exception as exc:
        LOG.exception("Postgres persistence failed (%s); JSON/CSV outputs retained", type(exc).__name__)
        saved = 0
    actionable = CAMPAIGN_START <= TODAY <= CAMPAIGN_END
    LOG.info("LinkedIn discovery complete: candidates=%d db_rows=%d window=%dd campaign_actionable=%s",
             len(rows), saved, WINDOW_DAYS, actionable)
    if not rows:
        LOG.warning("No candidate records. This is not evidence that no LinkedIn demand exists.")
    return 0

if __name__ == "__main__":
    sys.exit(main())

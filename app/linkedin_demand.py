"""Discover publicly indexed LinkedIn project and insights-talent demand signals.

Uses a search provider's public index only. It does not log into LinkedIn,
scrape authenticated pages, bypass controls, or message anyone. Results are
candidate signals, not proof of a consulting purchase.
"""
import os, re, json, logging, urllib.request
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
import psycopg2
from psycopg2.extras import RealDictCursor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("apex-linkedin-demand")
TAVILY = "https://api.tavily.com/search"
REGIONS = [
    ("United States", "United States"),
    ("Ireland", "Ireland"),
    ("Germany", "Germany"), ("France", "France"),
    ("Netherlands", "Netherlands"), ("Belgium", "Belgium"),
    ("Switzerland", "Switzerland"), ("Italy", "Italy"),
    ("Spain", "Spain"), ("Sweden", "Sweden"),
    ("Denmark", "Denmark"), ("Norway", "Norway"),
    ("Finland", "Finland"), ("Austria", "Austria"),
]
PROJECT_TERMS = [
    '"market research" OR "market sizing" OR CAGR OR "consumer insights"',
    '"competitive intelligence" OR "market intelligence" OR "customer research"',
    '"business consulting project" OR "consulting project" OR "research project"',
    '"data analytics" OR "consumer data" OR "market data" external consultant',
]
TALENT_TERMS = [
    '"Head of Insights" OR "Director of Insights" OR "VP Insights"',
    '"Consumer Insights" OR "Market Intelligence" OR "Market Research" lead',
    '"Data & Insights" OR "Commercial Analytics" OR "Strategy & Insights"',
]
BUYING_WORDS = re.compile(r"\b(looking for|seeking|need|needed|request for|rfp|project brief|"
                          r"consultant|consulting|agency|external partner|market research|"
                          r"consumer insights|market intelligence|cagr|market sizing|"
                          r"competitive intelligence|data insights|market data)\b", re.I)
ROLE_WORDS = re.compile(r"\b(head|director|vp|vice president|lead|manager|chief)\b", re.I)
EXCLUDE_COUNTRIES = {"UK", "United Kingdom", "India"}
def request_json(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
        headers={"Content-Type":"application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=35) as resp:
        return json.loads(resp.read().decode())
def search(query):
    key = os.getenv("TAVILY_API_KEY")
    if not key: raise RuntimeError("TAVILY_API_KEY is not configured")
    data = request_json(TAVILY, {"api_key":key, "query":query, "search_depth":"advanced",
        "topic":"general", "time_range":"week", "max_results":8,
        "include_answer":False, "include_raw_content":False})
    return data.get("results", [])
def company_from(title, content):
    # Prefer explicit LinkedIn job title patterns: "Role at Company | LinkedIn".
    m = re.search(r"\bat\s+(.+?)(?:\s*[|–-]\s*LinkedIn|$)", title, re.I)
    if m:
        name = m.group(1).strip(" -|")
        if 1 < len(name) < 90: return name
    # Post titles often begin with a company name; do not guess from arbitrary prose.
    first = re.split(r"[|–—:]", title)[0].strip()
    if 1 < len(first.split()) <= 6 and len(first) < 75 and not first.lower().startswith(("linkedin", "jobs", "people")):
        return first
    m = re.search(r"\b(?:at|with|for)\s+([A-Z][A-Za-z0-9&.' -]{1,55}?)\s+(?:is|are|seeks|seeking|looking|hiring|needs)\b", content)
    return m.group(1).strip() if m else None
def main():
    dsn = os.getenv("DATABASE_URL")
    if not dsn: raise RuntimeError("DATABASE_URL is not configured")
    now = datetime.now(timezone.utc)
    hits = {}
    for country, region in REGIONS:
        for kind, terms in (("PROJECT_BRIEF", PROJECT_TERMS), ("INSIGHTS_TALENT", TALENT_TERMS)):
            for term in terms:
                q = f'site:linkedin.com {region} {term} (posted OR hiring OR "looking for" OR seeking)'
                try:
                    for item in search(q):
                        url = (item.get("url") or "").strip()
                        host = urlparse(url).netloc.lower()
                        if "linkedin.com" not in host: continue
                        title = (item.get("title") or "").strip()
                        content = (item.get("content") or "").strip()
                        if not title or not content: continue
                        text_blob = title + " " + content
                        if not BUYING_WORDS.search(text_blob) and kind == "PROJECT_BRIEF": continue
                        if kind == "INSIGHTS_TALENT" and not ROLE_WORDS.search(text_blob): continue
                        published = item.get("published_date")
                        hits[url] = {"country":country, "kind":kind, "title":title,
                            "content":content[:3500], "url":url, "published":published}
                except Exception as exc:
                    log.warning("Search failed country=%s kind=%s error=%s", country, kind, type(exc).__name__)
    inserted = duplicate = stale = no_company = 0
    with psycopg2.connect(dsn, sslmode="require", connect_timeout=15) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='leads'")
            cols = {r["column_name"] for r in cur.fetchall()}
            for h in hits.values():
                company = company_from(h["title"], h["content"])
                if not company: no_company += 1; continue
                try:
                    dt = datetime.fromisoformat(h["published"].replace("Z","+00:00")) if h["published"] else None
                except Exception: dt = None
                if not dt or dt < now - timedelta(days=7): stale += 1; continue
                evidence = (f"LINKEDIN PUBLIC-INDEX CANDIDATE — NOT A CONFIRMED BUYER. "
                    f"Signal type: {h['kind']}. Specific fact: {h['title']}. "
                    f"Decision relevance: {h['content'][:900]}. Unknown to validate: "
                    f"whether this is an active external-data/consulting need, who owns it, "
                    f"budget, deadline and procurement route. Verify original post and company source. "
                    f"Published: {dt.isoformat()}.")
                values = {
                    "company_name":company, "country":h["country"], "sector":"LinkedIn demand signal",
                    "commercial_trigger":h["title"][:900], "evidence_summary":evidence[:4500],
                    "evidence_url":h["url"], "evidence_date":dt.date(),
                    "source_name":"LinkedIn (publicly indexed)", "fit_score":None,
                    "qualification_status":"P3"
                }
                use = {k:v for k,v in values.items() if k in cols}
                if "company_name" not in use or "evidence_url" not in use: continue
                keys = list(use)
                sql = f"INSERT INTO leads ({','.join(keys)}) VALUES ({','.join(['%s']*len(keys))})"
                if "evidence_url" in cols:
                    sql += " ON CONFLICT DO NOTHING"
                cur.execute(sql, [use[k] for k in keys])
                if cur.rowcount: inserted += 1
                else: duplicate += 1
    log.info("LinkedIn signal scan complete raw=%d inserted=%d duplicate=%d stale_or_undated=%d no_company=%d",
        len(hits), inserted, duplicate, stale, no_company)
    return {"raw":len(hits),"inserted":inserted,"duplicates":duplicate,
            "stale_or_undated":stale,"company_unresolved":no_company}
if __name__ == "__main__":
    print(json.dumps(main()))

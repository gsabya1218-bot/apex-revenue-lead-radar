import os, re, json, sqlite3, hashlib, logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlparse
import requests
import feedparser
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

APP_VERSION = "0.3.0"
DB_PATH = os.getenv("DB_PATH", "/tmp/apex_radar.sqlite3")
WINDOW_DAYS = int(os.getenv("WINDOW_DAYS", "7"))
COUNTRIES = ["United States", "Germany", "France", "Netherlands", "Ireland", "Switzerland", "Belgium", "Spain", "Italy", "Sweden", "Denmark", "Finland", "Norway", "Austria"]
EXCLUDE_TERMS = ["United Kingdom", "UK", "India"]
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("apex-radar")

app = FastAPI(title="Apex Revenue Lead Radar", version=APP_VERSION,
              description="Public-web discovery and evidence-gated commercial lead qualification.")

class ScanRequest(BaseModel):
    window_days: int = Field(default=7, ge=1, le=14)
    max_queries: int = Field(default=24, ge=1, le=40)

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS signals(
      id TEXT PRIMARY KEY, url TEXT UNIQUE, title TEXT, snippet TEXT, source TEXT,
      published TEXT, company TEXT, company_domain TEXT, signal_type TEXT,
      country TEXT, captured_at TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS leads(
      company_domain TEXT PRIMARY KEY, company TEXT, country TEXT, score INTEGER,
      priority TEXT, lead_type TEXT, fact TEXT, decision_deadline TEXT,
      unknown_gap TEXT, buyer_signal TEXT, evidence_json TEXT, updated_at TEXT)""")
    con.commit()
    return con

def query_set():
    regions = '("United States" OR USA OR Germany OR France OR Netherlands OR Ireland OR Switzerland OR Belgium OR Spain OR Italy OR Sweden OR Denmark OR Finland OR Norway OR Austria)'
    terms = [
      ('site:linkedin.com/posts ("seeking" OR "looking for" OR "need") ("market research" OR "consumer insights" OR "market sizing") ' + regions, "linkedin_project"),
      ('site:linkedin.com/posts ("consultant" OR "consulting project" OR "freelance") ("CAGR" OR "market data" OR "competitive intelligence") ' + regions, "linkedin_project"),
      ('site:linkedin.com/posts ("RFP" OR "vendor" OR "agency") ("consumer research" OR "market intelligence" OR "data analytics") ' + regions, "linkedin_project"),
      ('site:linkedin.com/jobs ("Head of Insights" OR "Director Consumer Insights" OR "Market Intelligence") ' + regions, "linkedin_role"),
      ('site:linkedin.com/jobs ("Head of Data" OR "Director Data Analytics" OR "Insights Lead") ("market" OR "consumer" OR "commercial") ' + regions, "linkedin_role"),
      ('site:linkedin.com/jobs ("Market Research" OR "Consumer Insights" OR "Competitive Intelligence") ("CAGR" OR "market sizing" OR "external data") ' + regions, "linkedin_role"),
      ('("market research consultant" OR "consumer insights consultant") ("project" OR "contract" OR "consultant") ' + regions, "project"),
      ('("CAGR analysis" OR "market sizing" OR "TAM SAM SOM") ("consultant" OR "research agency" OR "project") ' + regions, "project"),
      ('("external data" OR "market intelligence" OR "competitive intelligence") ("seeking" OR "looking for" OR "consultant") ' + regions, "project"),
      ('("consumer insights" OR "market research") ("Head of Insights" OR "Director Insights" OR "VP Insights") ' + regions, "buyer_role"),
      ('("new market entry" OR "geographic expansion" OR "product launch") ("consumer research" OR "market sizing" OR "CAGR") ' + regions, "business_trigger"),
      ('("nutraceutical" OR "ingredients CDMO" OR "food ingredients") ("market intelligence" OR "consumer insights" OR "commercial analytics") ' + regions, "sector_trigger"),
    ]
    return terms

def bing_rss(query):
    url = "https://www.bing.com/search?format=rss&q=" + quote(query)
    r = requests.get(url, timeout=20, headers={"User-Agent":"ApexMetricsLeadRadar/0.3 (+public-web research)"})
    r.raise_for_status()
    feed = feedparser.parse(r.content)
    out=[]
    for e in feed.entries:
        link = e.get("link","").strip()
        title = re.sub(r"<[^>]+>", " ", e.get("title","")).strip()
        summary = re.sub(r"<[^>]+>", " ", e.get("summary","")).strip()
        published = e.get("published") or e.get("updated") or ""
        if link and title:
            out.append({"url":link,"title":title,"snippet":summary,"published":published})
    return out

def parse_date(value):
    if not value: return None
    try:
        from email.utils import parsedate_to_datetime
        d=parsedate_to_datetime(value)
        if d.tzinfo is None: d=d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except Exception:
        try: return datetime.fromisoformat(value.replace("Z","+00:00")).astimezone(timezone.utc)
        except Exception: return None

def company_from(item):
    host=urlparse(item["url"]).netloc.lower().replace("www.","")
    title=item["title"]
    # Prefer a named employer suffix often present in job-result titles.
    m=re.search(r"\s(?:at|\-|\|)\s([A-Z][A-Za-z0-9&.,' -]{2,60})$", title)
    name=m.group(1).strip(" -|") if m else host.split(":")[0]
    if host.endswith("linkedin.com"): name = m.group(1).strip() if m else "Unresolved LinkedIn employer"
    return name,host

def infer_type(query_type, text):
    t=text.lower()
    if query_type.startswith("linkedin_project") or any(x in t for x in ["seeking consultant","looking for a consultant","consulting project","need a market research","rfp","request for proposal"]):
        return "posted_project_requirement"
    if "linkedin_role" in query_type or any(x in t for x in ["head of insights","director consumer insights","market intelligence lead","head of data"]):
        return "data_insights_hiring"
    if any(x in t for x in ["cagr","market sizing","market research","consumer insights","external data"]):
        return "market_data_intent"
    return "business_trigger"

def deadline(text):
    m=re.search(r"(?:by|before|deadline|due|submit(?:ted)? by|closing date)\s+([^.;,]{3,45})", text, re.I)
    return m.group(1).strip() if m else "Not stated publicly — confirm with buyer"

def country_hint(text):
    low=text.lower()
    for c in COUNTRIES:
        if c.lower() in low: return c
    if any(x in low for x in ["united states"," usa "," us-based","new york","california","boston","chicago","texas"]): return "United States"
    return "Unverified — country must be confirmed"

def allowed(item):
    text=(item["title"]+" "+item["snippet"]+" "+item["url"]).lower()
    return not any(x.lower() in text for x in EXCLUDE_TERMS) and not any(x in text for x in [".co.uk","uk/","india"])

def scan(window_days=7, max_queries=24):
    now=datetime.now(timezone.utc); cutoff=now-timedelta(days=window_days)
    terms=query_set()[:max_queries]
    collected=[]
    for q,typ in terms:
        try:
            for x in bing_rss(q):
                x["signal_type"]=infer_type(typ,x["title"]+" "+x["snippet"])
                x["source"]="Bing-indexed public web"
                x["country"]=country_hint(x["title"]+" "+x["snippet"])
                x["company"],x["company_domain"]=company_from(x)
                d=parse_date(x["published"])
                if d and d < cutoff: continue
                if not allowed(x): continue
                x["published"]=d.isoformat() if d else ""
                collected.append(x)
        except Exception as ex:
            log.warning("Search failed for %s: %s",typ,str(ex)[:180])
    # Deduplicate URLs, then persist only records with a URL and date within window (undated retained as unverified).
    unique={x["url"]:x for x in collected}
    con=db()
    for x in unique.values():
        sid=hashlib.sha256(x["url"].encode()).hexdigest()
        con.execute("INSERT OR IGNORE INTO signals VALUES(?,?,?,?,?,?,?,?,?,?,?)",
          (sid,x["url"],x["title"],x["snippet"],x["source"],x["published"],x["company"],x["company_domain"],x["signal_type"],x["country"],now.isoformat()))
    con.commit()
    # Company-level evidence gate: three distinct URLs, including one project/role intent signal.
    rows=con.execute("SELECT * FROM signals WHERE captured_at >= ?",((now-timedelta(days=window_days)).isoformat(),)).fetchall()
    groups={}
    for row in rows:
        key=row["company_domain"]
        if not key or key=="linkedin.com": continue
        groups.setdefault(key,[]).append(dict(row))
    created=0
    for domain,ev in groups.items():
        distinct={e["url"]:e for e in ev}
        ev=list(distinct.values())
        text=" ".join(e["title"]+" "+e["snippet"] for e in ev)
        has_project=any(e["signal_type"]=="posted_project_requirement" for e in ev)
        has_role=any(e["signal_type"]=="data_insights_hiring" for e in ev)
        has_market=any(e["signal_type"]=="market_data_intent" for e in ev)
        explicit_deadline=bool(re.search(r"\b(by|before|deadline|due|closing date)\b",text,re.I))
        # Search snippets are leads for investigation, never proof of procurement by themselves.
        score=min(100, 15*len(ev)+25*has_project+12*has_role+12*has_market+8*explicit_deadline)
        priority="P1" if has_project and len(ev)>=3 and explicit_deadline else ("P2" if len(ev)>=3 and (has_project or (has_role and has_market)) else "P3")
        lead_type="Verified buying signal" if has_project and explicit_deadline else ("Verified business trigger" if len(ev)>=3 else "Hypothesis — needs validation")
        fact=" | ".join(e["title"] for e in ev[:3])
        gap="The company’s actual external-data coverage, country/SKU/customer granularity, and decision owner are not established by public snippets; validate in discovery."
        buyer="Named decision-maker not verified from these search results; identify the role owner before outreach."
        con.execute("""INSERT INTO leads VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(company_domain) DO UPDATE SET company=excluded.company,country=excluded.country,score=excluded.score,
          priority=excluded.priority,lead_type=excluded.lead_type,fact=excluded.fact,decision_deadline=excluded.decision_deadline,
          unknown_gap=excluded.unknown_gap,buyer_signal=excluded.buyer_signal,evidence_json=excluded.evidence_json,updated_at=excluded.updated_at""",
          (domain,ev[0]["company"],ev[0]["country"],score,priority,lead_type,fact,deadline(text),gap,buyer,json.dumps(ev[:10]),now.isoformat()))
        created+=1
    con.commit(); count=con.execute("SELECT COUNT(*) FROM signals").fetchone()[0]; con.close()
    return {"status":"completed_with_public_indexed_search","window_days":window_days,"queries_run":len(terms),"new_urls":len(unique),"company_groups_updated":created,"stored_signals":count,"limitations":["LinkedIn coverage is limited to publicly indexed pages; this does not access private posts or member data.","Search snippets are discovery evidence, not buyer confirmation. Every P1/P2 must be manually source-checked before outreach.","Undated results are retained as unverified and must not be promoted to P1/P2."]}

@app.get("/health")
def health():
    return {"status":"ok","service":"Apex Revenue Lead Radar","version":APP_VERSION,"database":"sqlite_local","linkedin_mode":"publicly_indexed_only"}

@app.post("/scan")
def run_scan(req: ScanRequest, x_api_key: str = Header(default="")):
    key=os.getenv("RADAR_API_KEY","")
    if key and x_api_key != key: raise HTTPException(status_code=401,detail="Invalid API key")
    return scan(req.window_days,req.max_queries)

@app.get("/leads")
def get_leads(priority: str = "", limit: int = 100, x_api_key: str = Header(default="")):
    key=os.getenv("RADAR_API_KEY","")
    if key and x_api_key != key: raise HTTPException(status_code=401,detail="Invalid API key")
    con=db()
    if priority:
        rows=con.execute("SELECT * FROM leads WHERE priority=? ORDER BY score DESC LIMIT ?",(priority, min(limit,500))).fetchall()
    else:
        rows=con.execute("SELECT * FROM leads ORDER BY score DESC LIMIT ?",(min(limit,500),)).fetchall()
    con.close()
    out=[]
    for r in rows:
        d=dict(r); d["evidence"]=json.loads(d.pop("evidence_json")); out.append(d)
    return {"count":len(out),"leads":out,"qualification_note":"P1/P2 are candidate leads, not confirmed buyers. Verify source URLs, dates, company identity, buyer and actual project scope before outreach."}

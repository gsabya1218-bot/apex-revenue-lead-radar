"""High-precision discovery queue for urgent commercial data-gap signals.

This script only discovers candidates. It does not claim a buyer requirement:
public evidence must be reviewed against RESEARCH_STANDARD.md before P1/P2 status.
"""
import os, re, sys, time, logging, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html import unescape
from contextlib import closing
from email.utils import parsedate_to_datetime
import psycopg2

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("apex-discovery")

# Queries are intentionally centered on documented data/intelligence failure plus
# a commercial consequence, not generic expansion, hiring, or partnership news.
REGIONS = [
    ("United States", "US", "US:en"),
    ("Ireland", "IE", "IE:en"),
    ("Germany", "DE", "DE:en"),
    ("France", "FR", "FR:en"),
    ("Netherlands", "NL", "NL:en"),
    ("Belgium", "BE", "BE:en"),
    ("Switzerland", "CH", "CH:en"),
    ("Italy", "IT", "IT:en"),
    ("Spain", "ES", "ES:en"),
    ("Sweden", "SE", "SE:en"),
    ("Denmark", "DK", "DK:en"),
    ("Norway", "NO", "NO:en"),
    ("Finland", "FI", "FI:en"),
    ("Austria", "AT", "AT:en"),
]
QUERY_THEMES = [
    '"data quality" OR "data gaps" OR "incomplete data" company revenue margin',
    '"market intelligence" OR "competitive intelligence" data missing OR fragmented OR outdated',
    '"historical data" unavailable OR incomplete company customer product pricing',
    '"supplier visibility" OR "supply chain visibility" data gaps disruption manufacturer',
    '"pricing data" OR "customer data" fragmented OR unreliable company margin',
    '"missed deals" OR "missed acquisition targets" data M&A intelligence',
    '"manual data collection" OR "spreadsheet" data delays company decision',
    '"market data" unavailable OR unreliable launch expansion company',
]
ACTION = re.compile(r"\b(faces|facing|reports|reported|warns|warned|struggles|struggling|"
                    r"unable|cannot|can't|lacks|missing|delayed|delays|disrupted|"
                    r"disruption|shortfall|missed|fails|failure|failed|"
                    r"announces|announced|launches|launched|acquires|acquired|seeking|looking|hiring|requires|requiring|needs|searching|"
                    r"expands|expanded|cuts|cut|restructures|restructuring)\b", re.I)
DATA_GAP = re.compile(r"\b(data gap|data gaps|data quality|incomplete data|missing data|"
                      r"fragmented data|outdated data|stale data|unavailable data|"
                      r"historical data|market intelligence|competitive intelligence|"
                      r"customer data|pricing data|supplier visibility|manual data|"
                      r"data access|data reliability|inaccurate data)\b", re.I)
BUSINESS_PAIN = re.compile(r"\b(revenue|margin|profit|market share|customer churn|"
                           r"lost sales|missed deals|acquisition|launch|expansion|"
                           r"supplier|supply chain|capacity|pricing|regulatory deadline|"
                           r"competitive|customer demand|forecast)\b", re.I)
GENERIC = {"company","business","group","manufacturer","industry","market","report",
           "study","research","analysis","sector","supplier","startup","firm","the",
           "a","an","us","europe","european","american","global","new","major","leading"}

def clean(s):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()

def parse_date(value):
    try: return parsedate_to_datetime(value).date() if value else None
    except Exception: return None

def extract_company(title):
    match = ACTION.search(title)
    if not match: return None
    candidate = re.sub(r"^(breaking|exclusive|update)\s*:?\s*", "", title[:match.start()].strip(" -:|,.'\""), flags=re.I)
    words = candidate.split()
    if not 1 <= len(words) <= 6 or len(candidate) > 70: return None
    if any(w.lower().strip(".,:") in GENERIC for w in words[:2]): return None
    if not any(any(ch.isupper() for ch in w[1:]) or w.isupper() for w in words): return None
    return candidate

def fetch(region, gl, ceid, query):
    params = {"q": f"({query}) when:7d -UK -'United Kingdom' -India",
              "hl":"en-US","gl":gl,"ceid":ceid}
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent":"ApexMetricsRevenueRadar/2.0"})
    with urllib.request.urlopen(req, timeout=25) as response: root = ET.fromstring(response.read())
    rows=[]
    for item in root.findall("./channel/item"):
        title=clean(item.findtext("title")); link=(item.findtext("link") or "").strip()
        desc=clean(item.findtext("description")); pub=item.findtext("pubDate") or ""
        src=item.find("source")
        if title and link: rows.append((title,link,desc,pub,clean(src.text if src is not None else "Google News"),region))
    return rows


LINKEDIN_THEMES = [
    ('site:linkedin.com/posts ("seeking" OR "looking for" OR "need a consultant" OR "consultant required") ("market research" OR "consumer insights" OR "CAGR" OR "market sizing" OR "market data")', "linkedin_project"),
    ('site:linkedin.com/posts ("consulting project" OR "project brief" OR "scope of work" OR "freelance research") ("consumer" OR "market intelligence" OR "competitive intelligence" OR analytics)', "linkedin_project"),
    ('site:linkedin.com/posts ("RFP" OR "vendor search" OR "agency search") ("market research" OR "consumer insights" OR "CAGR" OR "external data")', "linkedin_project"),
    ('site:linkedin.com/jobs ("Head of Insights" OR "Director Consumer Insights" OR "Market Intelligence Lead" OR "Head of Data") ("CAGR" OR "market data" OR "consumer" OR "market research")', "linkedin_role"),
    ('site:linkedin.com/jobs ("Market Research" OR "Consumer Insights" OR "Data Analytics" OR "Competitive Intelligence") ("market sizing" OR "external data" OR "CAGR" OR "pricing data")', "linkedin_role"),
]

def fetch_linkedin(region, gl, ceid, query, signal_type):
    """Search-engine discovery of publicly indexed LinkedIn pages only; no login or private data."""
    params = {"q": f"({query}) when:7d -UK -'United Kingdom' -India",
              "hl": "en-US", "gl": gl, "ceid": ceid}
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "ApexMetricsRevenueRadar/2.1"})
    with urllib.request.urlopen(req, timeout=25) as response:
        root = ET.fromstring(response.read())
    rows = []
    for item in root.findall("./channel/item"):
        title = clean(item.findtext("title"))
        link = (item.findtext("link") or "").strip()
        desc = clean(item.findtext("description"))
        pub = item.findtext("pubDate") or ""
        src = item.find("source")
        if title and link and "linkedin.com" in link.lower():
            rows.append((title, link, desc, pub, "Publicly indexed LinkedIn", region, signal_type))
    return rows

def extract_linkedin_company(title, description):
    text = f"{title} {description}"
    patterns = [
        r"\b(?:at|with|for)\\s+([A-Z][A-Za-z0-9&.,'() -]{2,65})",
        r"\\bcompany\\s*[:=-]\\s*([A-Z][A-Za-z0-9&.,'() -]{2,65})",
        r"\\b(?:we are|we're)\\s+([A-Z][A-Za-z0-9&.,'() -]{2,55})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            candidate = match.group(1).strip(" .,:;|-")
            candidate = re.split(r"\\b(?:is|are|seeking|looking|hiring|needs|requires|for)\\b", candidate, maxsplit=1, flags=re.I)[0].strip()
            if 2 <= len(candidate) <= 65 and len(candidate.split()) <= 7:
                return candidate
    return None


def main():
    dsn=os.getenv("DATABASE_URL")
    if not dsn:
        log.error("DATABASE_URL missing; no records written"); return 2
    found={}
    for region,gl,ceid in REGIONS:
        for query in QUERY_THEMES:
            try:
                for row in fetch(region,gl,ceid,query): found[row[1]]=row
            except Exception as exc:
                log.warning("Feed failed region=%s error_type=%s",region,type(exc).__name__)
            time.sleep(0.25)
        log.info("Completed targeted discovery region=%s",region)

    inserted=0; rejected=0; duplicates=0; weak=0
    with closing(psycopg2.connect(dsn,sslmode="require",connect_timeout=15)) as conn:
        with conn:
            with conn.cursor() as cur:
                for title,url,desc,pub,source,country in found.values():
                    company=extract_company(title)
                    body=f"{title}. {desc}"
                    # Require data-gap evidence AND a material business consequence.
                    # This is a candidate filter, not proof of an actual purchase requirement.
                    if not company or not DATA_GAP.search(body) or not BUSINESS_PAIN.search(body):
                        rejected += 1; continue
                    dt=parse_date(pub)
                    if not dt or (datetime.now(timezone.utc).date()-dt).days > 7:
                        weak += 1; continue
                    cur.execute("SELECT 1 FROM leads WHERE evidence_url=%s LIMIT 1",(url,))
                    if cur.fetchone(): duplicates+=1; continue
                    summary=("DISCOVERY CANDIDATE — NOT YET QUALIFIED. "
                             "Data-gap phrase and business-impact phrase detected in public news text. "
                             "Verify primary source, actual internal-team limitation, executive owner, "
                             "deadline, external-data need, and Apex fit before P1/P2 classification. "
                             f"Headline: {title}. Source description: {desc}")[:2000]
                    cur.execute("""INSERT INTO leads
                        (company_name,country,commercial_trigger,evidence_summary,evidence_url,
                         evidence_date,source_name,fit_score)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,NULL)""",
                        (company,country,title[:1000],summary,url,dt,source or "Google News RSS"))
                    inserted+=1
    log.info("Discovery complete: raw_items=%d inserted_candidates=%d rejected_weak_match=%d "
             "stale_or_undated=%d duplicates=%d. Candidate records are NOT qualified leads.",
             len(found),inserted,rejected,weak,duplicates)
    return 0

if __name__=="__main__": sys.exit(main())

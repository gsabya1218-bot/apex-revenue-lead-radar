"""Collect recent public commercial signals from Google News RSS.

This is a discovery queue, not an automated buyer-qualification engine.
Every inserted record is marked research_required for human verification.
"""
import os
import re
import sys
import time
import logging
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html import unescape
from contextlib import closing

import psycopg2

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("apex-discovery")

QUERIES = [
    ("USA", '"food ingredients" OR "consumer goods" OR CPG expansion OR pricing OR acquisition'),
    ("USA", '"flavors and fragrances" OR nutraceutical OR biotech manufacturing expansion'),
    ("USA", '"electric vehicle" OEM supplier expansion OR restructuring OR market launch'),
    ("USA", '"private equity" portfolio company acquisition OR carve-out OR market expansion'),
    ("Europe", '"food ingredients" OR CPG OR consumer goods expansion OR acquisition -UK -India'),
    ("Europe", '"flavors and fragrances" OR biotech OR CDMO expansion OR capacity -UK -India'),
    ("Europe", '"industrial manufacturing" supply chain disruption OR acquisition OR expansion -UK -India'),
    ("Europe", '"private equity" portfolio company acquisition OR carve-out -UK -India'),
]
ACTION_WORDS = re.compile(
    r"\b(announces|announced|launches|launched|acquires|acquired|acquisition|"
    r"expands|expanded|expansion|opens|opened|plans|planned|invests|invested|"
    r"investment|partners|partnered|partnership|raises|raised|cuts|cut|"
    r"restructures|restructuring|exits|exited|sells|sold|files|filed|"
    r"recalls|recalled|reports|reported|warns|warned|secures|secured)\b",
    re.I,
)
GENERIC = {
    "company", "business", "group", "manufacturer", "manufacturer", "industry",
    "market", "report", "study", "research", "analysis", "sector", "supplier",
    "startup", "firm", "firm's", "the", "a", "an", "us", "europe", "european",
    "american", "global", "new", "major", "leading",
}


def clean_text(value):
    value = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", unescape(value)).strip()


def extract_company(title):
    """Only accept a plausible named lead-in before a commercial action verb."""
    match = ACTION_WORDS.search(title)
    if not match:
        return None
    candidate = title[:match.start()].strip(" -:|,.'\"")
    candidate = re.sub(r"^(breaking|exclusive|update)\s*:?\s*", "", candidate, flags=re.I)
    words = candidate.split()
    if not 1 <= len(words) <= 6 or len(candidate) < 2 or len(candidate) > 70:
        return None
    if any(w.lower().strip(".,:") in GENERIC for w in words[:2]):
        return None
    if not any(any(ch.isupper() for ch in w[1:]) or w.isupper() for w in words):
        return None
    return candidate


def fetch_feed(region, query):
    search = f"({query}) when:7d"
    params = {"q": search, "hl": "en-US", "gl": "US" if region == "USA" else "IE", "ceid": "US:en" if region == "USA" else "IE:en"}
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "ApexMetricsRevenueRadar/1.0"})
    with urllib.request.urlopen(req, timeout=25) as response:
        data = response.read()
    root = ET.fromstring(data)
    items = []
    for item in root.findall("./channel/item"):
        title = clean_text(item.findtext("title"))
        link = (item.findtext("link") or "").strip()
        description = clean_text(item.findtext("description"))
        pub = (item.findtext("pubDate") or "").strip()
        source_el = item.find("source")
        source = clean_text(source_el.text if source_el is not None else "Google News")
        if title and link:
            items.append((title, link, description, pub, source, region))
    return items


def parse_date(value):
    if not value:
        return None
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(value).date()
    except Exception:
        return None


def main():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        log.error("DATABASE_URL secret is missing; no records written.")
        return 2

    collected = {}
    for region, query in QUERIES:
        try:
            for row in fetch_feed(region, query):
                collected[row[1]] = row
            log.info("Fetched region=%s query=%s", region, query[:48])
        except Exception as exc:
            log.warning("Feed failed region=%s error_type=%s", region, type(exc).__name__)
        time.sleep(1)

    inserted = 0
    skipped_no_company = 0
    skipped_existing = 0
    with closing(psycopg2.connect(database_url, sslmode="require", connect_timeout=15)) as conn:
        with conn:
            with conn.cursor() as cur:
                for title, url, description, pub, source, region in collected.values():
                    company = extract_company(title)
                    if not company:
                        skipped_no_company += 1
                        continue
                    cur.execute("SELECT 1 FROM leads WHERE evidence_url = %s LIMIT 1", (url,))
                    if cur.fetchone():
                        skipped_existing += 1
                        continue
                    summary = (description or title)[:2000]
                    cur.execute(
                        """INSERT INTO leads
                           (company_name, country, commercial_trigger, evidence_summary,
                            evidence_url, evidence_date, source_name, fit_score, qualification_status)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, 'research_required')""",
                        (company, region, title[:1000], summary, url, parse_date(pub), source or "Google News RSS"),
                    )
                    inserted += 1
    log.info(
        "Discovery complete: fetched=%d inserted=%d duplicate_skips=%d "
        "company_extraction_skips=%d; all inserted leads require human verification.",
        len(collected), inserted, skipped_existing, skipped_no_company,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

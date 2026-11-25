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
    'site:linkedin.com/posts ("project brief" OR "consulting project" OR "independent consultant") ("external data" OR "market data" OR "consumer research" OR "competitive intelligence")',
    'site:linkedin.com/posts ("Head of Insights" OR "Consumer Insights Director" OR "Market Intelligence Lead" OR "Head of Data") ("looking for" OR "seeking" OR "need" OR "data provider") ("CAGR" OR "market data" OR "consumer panel" OR "syndicated data")',
]
HIRING_QUERIES = [
    'site:linkedin.com/jobs/view ("Head of Insights" OR "Director Consumer Insights" OR "Market Intelligence" OR "Head of Data Analytics")',
    'site:linkedin.com/jobs/view ("CAGR" OR "syndicated data" OR "market data" OR "consumer panel" OR "external data") (insights OR analytics OR strategy)',
    'site:linkedin.com/jobs/view ("competitive intelligence" OR "market research" OR "consumer data" OR "category insights" OR "external data providers") (director OR head OR lead OR manager)',
]

import hmac
import logging
import os
from contextlib import closing
from datetime import date
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("apex-radar")

app = FastAPI(title="Apex Revenue Lead Radar", version="0.2.0")


def db_connection():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    return psycopg2.connect(url, sslmode="require", connect_timeout=8)


def require_api_key(value: Optional[str]):
    expected = os.getenv("API_KEY")
    if not expected:
        raise HTTPException(status_code=503, detail="API key is not configured")
    if not value or not hmac.compare_digest(value, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


class LeadInput(BaseModel):
    company_name: str = Field(min_length=1, max_length=300)
    website: Optional[str] = None
    country: Optional[str] = None
    sector: Optional[str] = None
    commercial_trigger: Optional[str] = None
    evidence_summary: Optional[str] = None
    evidence_url: Optional[str] = None
    evidence_date: Optional[date] = None
    source_name: Optional[str] = None
    buyer_role: Optional[str] = None
    buyer_name: Optional[str] = None
    fit_score: Optional[int] = Field(default=None, ge=0, le=100)


@app.get("/")
def home():
    return {"status": "running", "service": "Apex Revenue Lead Radar", "version": "0.2.0"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/db-health")
def db_health():
    try:
        with closing(db_connection()) as conn:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
        return {"database": "connected"}
    except Exception:
        logger.exception("Database health check failed")
        raise HTTPException(status_code=503, detail="Database connection failed; check Render and Supabase settings")


@app.get("/agents")
def agents():
    return {
        "configured_agents": 30,
        "active_agents": 0,
        "status": "configuration_pending",
        "note": "The 30-agent workflows are not active yet."
    }


@app.get("/leads")
def list_leads(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    x_api_key: Optional[str] = Header(default=None)
):
    require_api_key(x_api_key)
    try:
        with closing(db_connection()) as conn:
            with conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        """SELECT id, company_name, website, country, sector,
                                  commercial_trigger, evidence_summary, evidence_url,
                                  evidence_date, source_name, buyer_role, buyer_name,
                                  fit_score, qualification_status, created_at, updated_at
                           FROM leads
                           ORDER BY created_at DESC
                           LIMIT %s OFFSET %s""",
                        (limit, offset)
                    )
                    rows = cur.fetchall()
        return {"leads": [dict(row) for row in rows], "count": len(rows)}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Lead retrieval failed")
        raise HTTPException(status_code=503, detail="Could not retrieve leads; verify the database setup")


@app.post("/leads")
def create_lead(lead: LeadInput, x_api_key: Optional[str] = Header(default=None)):
    require_api_key(x_api_key)
    try:
        values = lead.dict()
        with closing(db_connection()) as conn:
            with conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        """INSERT INTO leads
                           (company_name, website, country, sector, commercial_trigger,
                            evidence_summary, evidence_url, evidence_date, source_name,
                            buyer_role, buyer_name, fit_score)
                           VALUES
                           (%(company_name)s, %(website)s, %(country)s, %(sector)s,
                            %(commercial_trigger)s, %(evidence_summary)s, %(evidence_url)s,
                            %(evidence_date)s, %(source_name)s, %(buyer_role)s,
                            %(buyer_name)s, %(fit_score)s)
                           ON CONFLICT (LOWER(company_name), COALESCE(evidence_url, ''))
                           DO UPDATE SET updated_at = NOW()
                           RETURNING id, company_name, qualification_status, created_at""",
                        values
                    )
                    saved = cur.fetchone()
        return {"saved": True, "lead": dict(saved)}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Lead save failed")
        raise HTTPException(status_code=503, detail="Could not save lead; verify the SQL schema was applied")

import os
from typing import Optional
from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field
import psycopg
from psycopg.rows import dict_row

app = FastAPI(title="Apex Revenue Lead Radar", version="0.1.0")

def db():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    return psycopg.connect(url, row_factory=dict_row)

class LeadIn(BaseModel):
    company_name: str = Field(min_length=2, max_length=250)
    website: Optional[str] = None
    country: Optional[str] = None
    segment: Optional[str] = None
    trigger: Optional[str] = None
    evidence_url: Optional[str] = None
    evidence_summary: Optional[str] = None
    confidence: int = Field(default=0, ge=0, le=100)
    status: str = "needs_review"

@app.get("/")
def home():
    return {
        "service": "Apex Revenue Lead Radar",
        "status": "running",
        "docs": "/docs",
        "health": "/health",
        "scope": "USA and continental Europe, including Ireland; excludes UK and India"
    }

@app.get("/health")
def health():
    try:
        with db() as conn:
            conn.execute("SELECT 1")
        return {"status": "ok", "database": "connected"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database check failed: {type(exc).__name__}")

@app.get("/agents")
def agents():
    import json
    with open("config/agents.json", encoding="utf-8") as f:
        return json.load(f)

@app.get("/leads")
def list_leads(limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0)):
    try:
        with db() as conn:
            rows = conn.execute(
                """SELECT id, company_name, website, country, segment, trigger,
                          evidence_url, evidence_summary, confidence, status, created_at
                   FROM leads ORDER BY created_at DESC LIMIT %s OFFSET %s""",
                (limit, offset)
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) AS n FROM leads").fetchone()["n"]
        return {"total": total, "limit": limit, "offset": offset, "items": rows}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database query failed: {type(exc).__name__}")

@app.post("/leads")
def add_lead(payload: LeadIn, x_api_key: str = Header(default="")):
    expected = os.getenv("API_KEY", "")
    if not expected or x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid API key")
    try:
        with db() as conn:
            row = conn.execute(
                """INSERT INTO leads
                   (company_name, website, country, segment, trigger, evidence_url,
                    evidence_summary, confidence, status)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (company_name, evidence_url) DO UPDATE SET
                     website=EXCLUDED.website, country=EXCLUDED.country,
                     segment=EXCLUDED.segment, trigger=EXCLUDED.trigger,
                     evidence_summary=EXCLUDED.evidence_summary,
                     confidence=EXCLUDED.confidence, status=EXCLUDED.status,
                     updated_at=now()
                   RETURNING id, company_name, status, confidence""",
                (payload.company_name, payload.website, payload.country, payload.segment,
                 payload.trigger, payload.evidence_url, payload.evidence_summary,
                 payload.confidence, payload.status)
            ).fetchone()
        return row
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Could not save lead: {type(exc).__name__}")

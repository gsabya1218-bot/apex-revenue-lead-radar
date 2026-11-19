from fastapi import FastAPI

app = FastAPI(title="Apex Revenue Lead Radar")

@app.get("/")
def home():
    return {"status": "running", "service": "Apex Revenue Lead Radar"}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/agents")
def agents():
    return {"configured_agents": 30, "status": "configuration_pending"}

@app.get("/leads")
def leads():
    return {"leads": [], "count": 0}

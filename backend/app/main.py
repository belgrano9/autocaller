from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.db import init_db
from app.routers import auth, billing, forms, inbox, mode, outreach, venues

app = FastAPI(title="Devis Mariages API", version="0.1.0")

@app.on_event("startup")
def startup():
    init_db()

app.include_router(venues.router, prefix="/api")
app.include_router(outreach.router, prefix="/api")
app.include_router(mode.router, prefix="/api")
app.include_router(forms.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(billing.router, prefix="/api")
app.include_router(inbox.router, prefix="/api")

FRONTEND = Path(__file__).parent.parent.parent / "frontend"

@app.get("/")
@app.get("/fr")
@app.get("/en")
async def serve_landing():
    return FileResponse(FRONTEND / "landing.html")

@app.get("/dashboard")
async def serve_dashboard():
    return FileResponse(FRONTEND / "index.html")

# Clean URLs for the static legal pages the footer links to (StaticFiles
# does not append ".html", so /legal etc. would otherwise 404).
@app.get("/pricing")
async def serve_pricing():
    return FileResponse(FRONTEND / "pricing.html")

@app.get("/settings")
async def serve_settings():
    return FileResponse(FRONTEND / "settings.html")

@app.get("/legal")
async def serve_legal():
    return FileResponse(FRONTEND / "legal.html")

@app.get("/privacy")
async def serve_privacy():
    return FileResponse(FRONTEND / "privacy.html")

@app.get("/terms")
async def serve_terms():
    return FileResponse(FRONTEND / "terms.html")

@app.get("/api/health")
async def health():
    return {"status": "ok"}

app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")

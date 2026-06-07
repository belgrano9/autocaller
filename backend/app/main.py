from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routers import mode, outreach, venues

app = FastAPI(title="Devis Mariages API", version="0.1.0")

app.include_router(venues.router, prefix="/api")
app.include_router(outreach.router, prefix="/api")
app.include_router(mode.router, prefix="/api")


from fastapi.responses import FileResponse

FRONTEND = Path(__file__).parent.parent.parent / "frontend"


@app.get("/")
@app.get("/fr")
@app.get("/en")
async def serve_index():
    return FileResponse(FRONTEND / "index.html")


@app.get("/api/health")
async def health():
    return {"status": "ok"}


app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")

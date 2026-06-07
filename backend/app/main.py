from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routers import mode, test_send, venues

app = FastAPI(title="Devis Mariages API", version="0.1.0")

app.include_router(venues.router, prefix="/api")
app.include_router(test_send.router, prefix="/api")
app.include_router(mode.router, prefix="/api")


@app.get("/api/health")
async def health():
    return {"status": "ok"}


FRONTEND = Path(__file__).parent.parent.parent / "frontend"
app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")

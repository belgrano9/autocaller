import json
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/forms", tags=["forms"])

FORMS_DIR = Path(__file__).parent.parent.parent.parent / "db" / "forms"

SLUG_RE = re.compile(r"^[a-z0-9_]+$")


@router.get("/{slug}")
def get_form_schema(slug: str):
    if not SLUG_RE.match(slug):
        raise HTTPException(status_code=404, detail="Form schema not found")
    path = FORMS_DIR / f"{slug}.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Form schema not found")
    return json.loads(path.read_text(encoding="utf-8"))

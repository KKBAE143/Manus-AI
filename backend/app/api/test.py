from fastapi import APIRouter
import sys, os
router = APIRouter()

@router.get("/api/v1/test_escape")
def test_escape():
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../..")))
    from app.services.manuscript_pipeline import escape_typst
    return {"result": repr(escape_typst("<1 minute"))}

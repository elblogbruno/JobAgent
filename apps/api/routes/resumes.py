"""The CV library: every resume in Reactive Resume, and which one is the master.

The master CV is the source of truth for role discovery and for every tailored
derivative, so choosing it is a deliberate act with a visible consequence: the
capability graph and the role map need rebuilding afterwards.
"""

import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.candidate_profile.profile import CandidateProfileLoader
from packages.persistence.database import get_db
from packages.persistence.models import ApplicationRunORM
from packages.reactive_resume.client import ReactiveResumeClient, ReactiveResumeError
from packages.reactive_resume.models import ResumeDetail
from packages.role_discovery.resume_digest import build_resume_digest

router = APIRouter(prefix="/api/resumes", tags=["Resumes"])

#: Rendering a PDF in Reactive Resume takes a second or two, which is far too slow
#: for a grid of previews. Renders are cached per resume version on disk.
PREVIEW_CACHE = Path("artifacts/resumes/previews")


def _unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=502,
        detail=(
            f"Could not reach Reactive Resume: {exc}. Check REACTIVE_RESUME_BASE_URL "
            "and REACTIVE_RESUME_API_KEY."
        ),
    )


@router.get("")
async def list_resumes():
    """Lists every resume, flagging the one currently used as the master CV."""
    profile = CandidateProfileLoader.get()
    master_id = profile.reactive_resume.master_resume_id

    try:
        resumes = await ReactiveResumeClient().list_resumes()
    except Exception as exc:
        raise _unavailable(exc)

    items = [
        {
            "id": item.id,
            "name": item.name,
            "slug": item.slug,
            "tags": item.tags,
            "locked": item.locked,
            "isPublic": item.isPublic,
            "isMaster": item.id == master_id,
            "createdAt": item.createdAt.isoformat() if item.createdAt else None,
            "updatedAt": item.updatedAt.isoformat() if item.updatedAt else None,
        }
        for item in resumes
    ]
    items.sort(key=lambda item: (not item["isMaster"], (item["updatedAt"] or ""), item["name"]))

    return {
        "count": len(items),
        "masterResumeId": master_id,
        "masterResumeName": profile.reactive_resume.master_resume_name,
        "masterResumeFound": any(item["isMaster"] for item in items),
        "resumes": items,
    }


@router.get("/{resume_id}/pdf")
async def get_resume_pdf(
    resume_id: str,
    v: Optional[str] = Query(default=None, description="Resume version, used as the cache key"),
    download: bool = Query(default=False),
):
    """Streams the rendered PDF, so the dashboard can preview a CV inline.

    The browser cannot call Reactive Resume directly: the API key must not leave the
    server. Renders are cached per version, because a grid of previews would
    otherwise re-render every CV on every visit.
    """
    cached = _cache_path(resume_id, v)
    if cached.exists() and cached.stat().st_size > 0:
        data = cached.read_bytes()
    else:
        try:
            data = await ReactiveResumeClient().download_resume_pdf(resume_id)
        except ReactiveResumeError as exc:
            raise HTTPException(status_code=404, detail=f"Resume not found: {exc}")
        except Exception as exc:
            raise _unavailable(exc)

        if not data.startswith(b"%PDF"):
            raise HTTPException(
                status_code=502,
                detail="Reactive Resume did not return a PDF for this resume.",
            )
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(data)

    disposition = "attachment" if download else "inline"
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'{disposition}; filename="{_safe_name(resume_id)}.pdf"',
            # Immutable only when the caller pinned a version.
            "Cache-Control": "private, max-age=3600" if v else "private, max-age=60",
        },
    )


@router.get("/{resume_id}")
async def get_resume_detail(resume_id: str):
    """One resume, with the digest role discovery actually reads."""
    profile = CandidateProfileLoader.get()
    try:
        resume = await ReactiveResumeClient().get_resume(resume_id)
    except ReactiveResumeError as exc:
        raise HTTPException(status_code=404, detail=f"Resume not found: {exc}")
    except Exception as exc:
        raise _unavailable(exc)

    return {
        "id": resume.id,
        "name": resume.name,
        "slug": resume.slug,
        "tags": resume.tags,
        "locked": resume.locked,
        "isMaster": resume.id == profile.reactive_resume.master_resume_id,
        "basics": resume.data.basics.model_dump(mode="json"),
        "sections": _section_summary(resume),
        "digest": build_resume_digest(resume, max_chars=6000),
    }


@router.put("/master")
async def set_master_resume(payload: Dict[str, Any] = Body(...)):
    """Points the candidate profile at a different master CV.

    Everything role discovery knows about the candidate is derived from this
    document, so the response says plainly that the role map is now stale.
    """
    resume_id = str(payload.get("resumeId") or payload.get("resume_id") or "").strip()
    if not resume_id:
        raise HTTPException(status_code=400, detail="resumeId is required")

    try:
        resume = await ReactiveResumeClient().get_resume(resume_id)
    except ReactiveResumeError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"No resume with id {resume_id} in Reactive Resume: {exc}",
        )
    except Exception as exc:
        raise _unavailable(exc)

    profile = CandidateProfileLoader.get()
    data = profile.model_dump()
    data["reactive_resume"]["master_resume_id"] = resume.id
    data["reactive_resume"]["master_resume_name"] = resume.name
    updated = CandidateProfileLoader.save(data)

    return {
        "status": "success",
        "masterResumeId": updated.reactive_resume.master_resume_id,
        "masterResumeName": updated.reactive_resume.master_resume_name,
        "roleMapStale": True,
        "message": (
            f"'{resume.name}' is now the master CV. Run role discovery again so the "
            "capability graph and the role map are rebuilt from it."
        ),
    }


def _safe_name(value: str) -> str:
    """A filesystem-safe stem. Ids come from the URL, so they are never trusted."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", value)
    return cleaned[:80] or "resume"


def _cache_path(resume_id: str, version: Optional[str]) -> Path:
    stamp = hashlib.sha256((version or "latest").encode("utf-8")).hexdigest()[:12]
    return PREVIEW_CACHE / f"{_safe_name(resume_id)}_{stamp}.pdf"


def _section_summary(resume: ResumeDetail) -> List[Dict[str, Any]]:
    """Counts the visible entries per section, so the UI can show substance."""
    summary: List[Dict[str, Any]] = []
    for key, section in (resume.data.sections or {}).items():
        if key in ("picture",):
            continue
        items: Optional[list] = None
        name = key
        visible = True
        if isinstance(section, dict):
            raw_items = section.get("items")
            items = raw_items if isinstance(raw_items, list) else None
            name = str(section.get("name") or key)
            visible = section.get("visible", True) is not False
        elif isinstance(section, list):
            items = section

        count = 0
        if items:
            count = sum(
                1 for item in items if not (isinstance(item, dict) and item.get("visible") is False)
            )
        summary.append({"key": key, "name": name, "items": count, "visible": visible})

    summary.sort(key=lambda entry: entry["items"], reverse=True)
    return summary


@router.delete("/{resume_id}")
async def delete_resume(resume_id: str, db: AsyncSession = Depends(get_db)):
    """Deletes a CV from Reactive Resume.

    The master CV is refused: everything the system knows about the candidate is
    derived from it, so deleting it by accident would be expensive to undo.
    Reactive Resume has no undo either, which is why the dashboard asks first.
    """
    profile = CandidateProfileLoader.get()
    if resume_id == profile.reactive_resume.master_resume_id:
        raise HTTPException(
            status_code=409,
            detail=("This is your master CV. Choose a different master first, then delete it."),
        )

    try:
        deleted = await ReactiveResumeClient().delete_resume(resume_id)
    except ReactiveResumeError as exc:
        raise HTTPException(status_code=404, detail=f"Resume not found: {exc}")
    except Exception as exc:
        raise _unavailable(exc)

    if not deleted:
        raise HTTPException(status_code=502, detail="Reactive Resume refused the deletion.")

    # An application pointing at a CV that no longer exists would offer a
    # download that 410s, so the reference goes with it.
    result = await db.execute(
        select(ApplicationRunORM).where(ApplicationRunORM.reactive_resume_resume_id == resume_id)
    )
    detached = 0
    for run in result.scalars().all():
        run.reactive_resume_resume_id = None
        detached += 1
    await db.flush()

    for cached in PREVIEW_CACHE.glob(f"{_safe_name(resume_id)}_*.pdf"):
        cached.unlink(missing_ok=True)

    return {
        "status": "success",
        "id": resume_id,
        "detachedApplications": detached,
        "message": "CV deleted from Reactive Resume.",
    }

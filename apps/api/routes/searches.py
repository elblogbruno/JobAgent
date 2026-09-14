"""Search query API: the slate the extension and dashboard turn into one-click searches."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.enums import SearchProviderId, SearchQueryStatus
from packages.domain.role_discovery import JobSearchQuerySpec
from packages.persistence.database import get_db
from packages.role_discovery.service import RoleDiscoveryService
from packages.search_providers.registry import all_providers, resolve_search_url

router = APIRouter(prefix="/api/searches", tags=["Search Strategy"])


@router.get("/providers")
async def list_providers():
    return {"providers": [provider.describe() for provider in all_providers()]}


@router.get("")
async def list_searches(
    include_inactive: bool = Query(default=False),
    role: Optional[str] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    specs = await RoleDiscoveryService(db).list_search_queries(
        include_inactive=include_inactive, role_key=role
    )
    if provider:
        specs = [spec for spec in specs if spec.provider.value == provider]
    return {"count": len(specs), "searches": [spec.to_api_dict() for spec in specs]}


@router.get("/inbox")
async def search_inbox(db: AsyncSession = Depends(get_db)):
    """The Search Inbox: everything worth clicking today, grouped and ranked.

    Queries are grouped by role family, and the same query across several providers
    collapses into one row with one button per provider. Exploratory searches are
    kept in their own section so trying something unproven is a deliberate act.
    """
    service = RoleDiscoveryService(db)
    specs = await service.list_search_queries()
    role_map = await service.get_role_map()

    best = _group(spec for spec in specs if not spec.is_exploratory)
    explore = _group(spec for spec in specs if spec.is_exploratory)

    return {
        "generatedAt": datetime.utcnow().isoformat(),
        "roleMapVersion": role_map.version if role_map else None,
        "sections": [
            {"id": "best", "title": "Best matches", "groups": best},
            {"id": "explore", "title": "Explore", "groups": explore},
        ],
        "totals": {
            "searches": len(specs),
            "exploratory": sum(1 for spec in specs if spec.is_exploratory),
            "searchesOpened": sum(spec.stats.searches_opened for spec in specs),
            "jobsImported": sum(spec.stats.jobs_imported for spec in specs),
            "highMatchJobsImported": sum(spec.stats.high_match_jobs_imported for spec in specs),
            "applicationsGenerated": sum(spec.stats.applications_generated for spec in specs),
            "interviewsProduced": sum(spec.stats.interviews_produced for spec in specs),
        },
    }


@router.post("")
async def create_search(
    payload: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """Adds a query by hand. Manual queries are never archived by a regeneration."""
    query_text = str(payload.get("query", "")).strip()
    if not query_text:
        raise HTTPException(status_code=400, detail="query is required")

    try:
        provider = SearchProviderId(str(payload.get("provider", "linkedin")).strip().lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"provider must be one of {[p.value for p in SearchProviderId]}",
        )

    spec = JobSearchQuerySpec(
        role_id=str(payload.get("roleId", "role_manual")),
        role_title=str(payload.get("roleTitle", "")),
        group_label=str(payload.get("groupLabel", "Manual searches")),
        label=str(payload.get("label", "")).strip() or query_text[:60],
        query=query_text,
        provider=provider,
        location=payload.get("location"),
        remote=payload.get("remote"),
        priority=int(payload.get("priority", 60)),
        is_exploratory=bool(payload.get("isExploratory", False)),
        created_by="user",
    )
    spec.resolved_url = resolve_search_url(spec)

    orm = await RoleDiscoveryService(db).query_repo.create(spec)
    spec.id = orm.id
    return {"status": "success", "search": spec.to_api_dict()}


@router.patch("/{query_id}")
async def update_search(
    query_id: str,
    payload: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
):
    status_value: Optional[SearchQueryStatus] = None
    if "status" in payload and payload["status"] is not None:
        try:
            status_value = SearchQueryStatus(str(payload["status"]).strip().lower())
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"status must be one of {[s.value for s in SearchQueryStatus]}",
            )

    priority = payload.get("priority")
    repo = RoleDiscoveryService(db).query_repo
    orm = await repo.update_query(
        query_id,
        priority=int(priority) if priority is not None else None,
        status=status_value,
        label=payload.get("label"),
    )
    if orm is None:
        raise HTTPException(status_code=404, detail="Search query not found")

    from packages.persistence.role_repositories import query_from_orm

    spec = query_from_orm(orm)
    spec.resolved_url = resolve_search_url(spec)
    await repo.update_query(query_id, resolved_url=spec.resolved_url)
    return {"status": "success", "search": spec.to_api_dict()}


@router.delete("/{query_id}")
async def archive_search(query_id: str, db: AsyncSession = Depends(get_db)):
    repo = RoleDiscoveryService(db).query_repo
    if await repo.update_query(query_id, status=SearchQueryStatus.ARCHIVED) is None:
        raise HTTPException(status_code=404, detail="Search query not found")
    return {"status": "success", "queryId": query_id}


@router.post("/{query_id}/opened")
async def record_search_opened(query_id: str, db: AsyncSession = Depends(get_db)):
    """Called when the user actually clicks a search, for attribution."""
    if not await RoleDiscoveryService(db).record_search_opened(query_id):
        raise HTTPException(status_code=404, detail="Search query not found")
    return {"status": "success", "queryId": query_id}


@router.get("/{query_id}/performance")
async def search_performance(query_id: str, db: AsyncSession = Depends(get_db)):
    service = RoleDiscoveryService(db)
    orm = await service.query_repo.get_by_id(query_id)
    if orm is None:
        raise HTTPException(status_code=404, detail="Search query not found")

    from packages.persistence.role_repositories import query_from_orm

    spec = query_from_orm(orm)
    jobs = await service.job_repo.list_jobs(limit=50, search_query_id=query_id)
    return {
        "search": spec.to_api_dict(),
        "jobs": [
            {
                "id": job.id,
                "company": job.company,
                "role": job.role,
                "matchScore": job.match_score,
                "status": job.status,
                "discoveredAt": job.discovered_at.isoformat() if job.discovered_at else None,
            }
            for job in jobs
        ],
    }


def _group(specs) -> List[Dict[str, Any]]:
    """Groups by role family, collapsing one query across providers into one row."""
    groups: Dict[str, Dict[str, Any]] = {}

    for spec in specs:
        group_label = spec.group_label or spec.role_title or "Recommended searches"
        group = groups.setdefault(
            group_label,
            {"label": group_label, "priority": 0, "searches": {}},
        )
        group["priority"] = max(group["priority"], spec.priority)

        row_key = f"{spec.label.lower()}|{spec.query.lower()}|{spec.location or ''}"
        row = group["searches"].setdefault(
            row_key,
            {
                "label": spec.label,
                "query": spec.query,
                "roleId": spec.role_id,
                "roleTitle": spec.role_title,
                "location": spec.location,
                "remote": spec.remote,
                "priority": spec.priority,
                "isExploratory": spec.is_exploratory,
                "targets": [],
            },
        )
        row["priority"] = max(row["priority"], spec.priority)
        row["targets"].append(
            {
                "queryId": spec.id,
                "provider": spec.provider.value,
                "url": spec.resolved_url,
                "stats": spec.to_api_dict()["stats"],
            }
        )

    rendered = []
    for group in sorted(groups.values(), key=lambda g: g["priority"], reverse=True):
        searches = sorted(group["searches"].values(), key=lambda row: row["priority"], reverse=True)
        rendered.append(
            {"label": group["label"], "priority": group["priority"], "searches": searches}
        )
    return rendered

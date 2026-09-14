"""Role Discovery API: the role map, the capability graph and the learning loop."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.enums import RoleCategory
from packages.persistence.database import get_db
from packages.role_discovery.service import RoleDiscoveryService

router = APIRouter(prefix="/api/roles", tags=["Role Discovery"])


@router.get("/map")
async def get_role_map(db: AsyncSession = Depends(get_db)):
    """The current role map, grouped the way the dashboard and extension show it."""
    service = RoleDiscoveryService(db)
    role_map = await service.get_role_map()
    if role_map is None:
        return {
            "exists": False,
            "message": "No role map yet. POST /api/roles/discover to build one.",
            "primary": [],
            "secondary": [],
            "exploratory": [],
            "avoid": [],
            "proposed": [],
        }

    queries = await service.list_search_queries()
    counts: dict = {}
    for spec in queries:
        counts[spec.role_id] = counts.get(spec.role_id, 0) + 1

    def render(role):
        payload = role.to_api_dict()
        payload["searchCount"] = counts.get(role.id, 0)
        return payload

    return {
        "exists": True,
        "version": role_map.version,
        "generatedBy": role_map.generated_by,
        "generatedAt": role_map.generated_at.isoformat(),
        "notes": role_map.notes,
        "industries": role_map.industries,
        "companyTypes": role_map.company_types,
        "roleFamilies": [family.model_dump(mode="json") for family in role_map.role_families],
        "capabilityGaps": [gap.model_dump(mode="json") for gap in role_map.capability_gaps],
        "primary": [render(role) for role in role_map.primary],
        "secondary": [render(role) for role in role_map.secondary],
        "exploratory": [render(role) for role in role_map.stretch],
        "avoid": [render(role) for role in role_map.avoid],
        "proposed": [
            render(role) for role in role_map.roles if role.proposal_status.value == "proposed"
        ],
    }


@router.get("/capability-graph")
async def get_capability_graph(db: AsyncSession = Depends(get_db)):
    graph = await RoleDiscoveryService(db).get_capability_graph()
    if graph is None:
        raise HTTPException(
            status_code=404,
            detail="No capability graph yet. POST /api/roles/discover to build one.",
        )

    by_kind: dict = {}
    for node in graph.nodes:
        by_kind.setdefault(node.kind.value, []).append(node.model_dump(mode="json"))

    return {
        "version": graph.version,
        "generatedBy": graph.generated_by,
        "generatedAt": graph.generated_at.isoformat(),
        "summary": graph.summary,
        "notes": graph.notes,
        "seniority": graph.seniority.model_dump(mode="json"),
        "facets": by_kind,
        "clusters": [cluster.model_dump(mode="json") for cluster in graph.clusters],
        "constraints": graph.constraints,
    }


@router.post("/discover")
async def discover_roles(
    use_llm: Optional[bool] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Rebuilds the capability graph, the role map and the search slate.

    Runs inline: it is a handful of model calls and the caller wants the result.
    """
    try:
        summary = await RoleDiscoveryService(db).refresh(use_llm=use_llm)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Role discovery failed: {exc}")
    return {"status": "success", **summary}


@router.post("/searches/regenerate")
async def regenerate_searches(
    use_llm: Optional[bool] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Rebuilds search queries from the stored role map without re-deriving roles."""
    try:
        strategy = await RoleDiscoveryService(db).regenerate_searches(use_llm=use_llm)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {
        "status": "success",
        "queries": len(strategy.queries),
        "notes": strategy.notes,
    }


@router.post("/learn")
async def learn_from_market(
    use_llm: Optional[bool] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Retunes query priorities and proposes new roles from imported jobs."""
    try:
        report = await RoleDiscoveryService(db).learn_from_market(use_llm=use_llm)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {
        "status": "success",
        "summary": report.summary,
        "adjustments": [a.model_dump(mode="json") for a in report.adjustments],
        "proposedRoles": [role.to_api_dict() for role in report.proposed_roles],
        "autoAcceptedRoleIds": report.auto_accepted_role_ids,
    }


@router.get("/{role_key}")
async def get_role_detail(role_key: str, db: AsyncSession = Depends(get_db)):
    service = RoleDiscoveryService(db)
    role_map = await service.get_role_map()
    role = role_map.role(role_key) if role_map else None
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found in the active role map.")

    queries = await service.list_search_queries(include_inactive=True, role_key=role_key)
    return {
        **role.to_api_dict(),
        "searches": [spec.to_api_dict() for spec in queries],
    }


@router.post("/{role_key}/accept")
async def accept_role(role_key: str, db: AsyncSession = Depends(get_db)):
    """Adopts a proposed role and generates its searches immediately."""
    if not await RoleDiscoveryService(db).accept_role(role_key):
        raise HTTPException(status_code=404, detail="Role not found in the active role map.")
    return {"status": "success", "roleId": role_key, "message": "Role accepted."}


@router.post("/{role_key}/reject")
async def reject_role(role_key: str, db: AsyncSession = Depends(get_db)):
    """Rejects a role and disables its searches."""
    if not await RoleDiscoveryService(db).reject_role(role_key):
        raise HTTPException(status_code=404, detail="Role not found in the active role map.")
    return {"status": "success", "roleId": role_key, "message": "Role rejected."}


@router.patch("/{role_key}/category")
async def set_role_category(
    role_key: str,
    category: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    try:
        parsed = RoleCategory(category.strip().lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"category must be one of {[c.value for c in RoleCategory]}",
        )
    service = RoleDiscoveryService(db)
    if await service.role_repo.update_role(role_key, category=parsed) is None:
        raise HTTPException(status_code=404, detail="Role not found in the active role map.")
    return {"status": "success", "roleId": role_key, "category": parsed.value}

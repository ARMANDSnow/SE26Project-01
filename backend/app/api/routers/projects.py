from __future__ import annotations

import json
from typing import Any, Literal, cast

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...auth.dependencies import CurrentUser
from ...db.connection import connect
from ...repositories.projects import (
    add_project_item,
    create_project,
    create_project_analysis_run,
    delete_project,
    get_project,
    get_latest_project_analysis,
    get_project_artifact,
    get_project_citation_evidence,
    list_project_citation_refs,
    list_project_artifacts,
    list_projects,
    project_backlinks,
    remove_project_item,
    reorder_project_items,
    set_project_status,
    update_project,
    validate_project_inputs,
)
from ...repositories.research import ResearchConflictError, ResearchNotFoundError
from ...repositories.research import request_action, resume_run, retry_run
from ...services.research import ResearchExecutor
from ...services.research_contracts import ResearchGraph, ResearchGraphEdge, ResearchGraphNode


router = APIRouter(prefix="/api/research/projects", tags=["research-projects"])
PRIVATE_NO_STORE = "private, no-store"
VIEW_TYPES = {
    "topic-clusters": "topic_clusters",
    "topic_clusters": "topic_clusters",
    "timeline": "research_timeline",
    "research_timeline": "research_timeline",
    "graph": "research_graph",
    "research_graph": "research_graph",
    "research_landscape_plan": "research_landscape_plan",
    "project_analysis_validation": "project_analysis_validation",
}


class StrictApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectCreateRequest(StrictApiModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4_000)


class ProjectUpdateRequest(StrictApiModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4_000)

    @model_validator(mode="after")
    def has_change(self) -> ProjectUpdateRequest:
        if self.title is None and self.description is None:
            raise ValueError("project update requires a title or description")
        return self


class ProjectItemCreateRequest(StrictApiModel):
    item_type: Literal["run", "paper", "research_report"]
    run_id: str | None = Field(default=None, max_length=100)
    paper_id: int | None = Field(default=None, ge=1)
    artifact_id: str | None = Field(default=None, max_length=100)
    artifact_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def strict_item_identity(self) -> ProjectItemCreateRequest:
        valid = (
            self.item_type == "run"
            and self.run_id is not None
            and self.paper_id is None
            and self.artifact_id is None
            and self.artifact_version is None
        ) or (
            self.item_type == "paper"
            and self.paper_id is not None
            and self.run_id is None
            and self.artifact_id is None
            and self.artifact_version is None
        ) or (
            self.item_type == "research_report"
            and self.artifact_id is not None
            and self.artifact_version is not None
            and self.run_id is None
            and self.paper_id is None
        )
        if not valid:
            raise ValueError("project item identity does not match item_type")
        return self


class ProjectItemPositionRequest(StrictApiModel):
    position: int = Field(ge=0, le=999)


class ProjectItemReorderRequest(StrictApiModel):
    item_ids: list[str] = Field(min_length=1, max_length=500)


def _item_dto(item: dict[str, Any], *, position: int | None = None) -> dict[str, Any]:
    dependency_status = "current" if item.get("status") == "valid" else str(item.get("status", "inaccessible"))
    result = {
        key: item.get(key)
        for key in (
            "id", "project_id", "item_type", "run_id", "paper_id", "artifact_id",
            "artifact_version", "source_hash_snapshot", "position", "added_at", "updated_at",
        )
    }
    result["position"] = int(item.get("position", position or 0))
    result["dependency_status"] = dependency_status
    if dependency_status == "inaccessible":
        # A tombstone intentionally excludes source identity, title, and content.
        return result
    source: dict[str, Any] = item["source"] if isinstance(item.get("source"), dict) else {}
    item_type = str(item.get("item_type", ""))
    if item_type == "run":
        result["title"] = source.get("title")
        result["subtitle"] = source.get("goal")
    elif item_type == "paper":
        result["title"] = source.get("title")
        authors = source.get("authors")
        result["subtitle"] = "、".join(str(author) for author in authors[:3]) if isinstance(authors, list) else None
    elif item_type == "research_report":
        content: dict[str, Any] = source["content"] if isinstance(source.get("content"), dict) else {}
        result["title"] = content.get("topic") or content.get("title") or f"研究报告 v{item.get('artifact_version')}"
        result["subtitle"] = "固定报告版本"
        result["source_run_id"] = source.get("run_id")
    return result


def _artifact_dto(item: dict[str, Any]) -> dict[str, Any]:
    dependency_status = str(item.get("dependency_status", "stale"))
    snapshot = item.get("input_snapshot")
    if not isinstance(snapshot, dict):
        encoded = item.get("input_snapshot_json")
        try:
            snapshot = json.loads(encoded) if isinstance(encoded, str) else {}
        except json.JSONDecodeError:
            snapshot = {}
        if not isinstance(snapshot, dict):
            snapshot = {}
    inputs = snapshot.get("items", []) if isinstance(snapshot, dict) else []
    input_item_ids = [str(value["id"]) for value in inputs if isinstance(value, dict) and value.get("id")]
    content = item.get("content") if dependency_status == "current" else None
    citation_keys = content.get("citation_keys", []) if isinstance(content, dict) else []
    status_value = str(item.get("status", "stale"))
    if dependency_status != "current":
        status_value = dependency_status
    return {
        "id": str(item["id"]),
        "project_id": str(item["project_id"]),
        "artifact_type": str(item["artifact_type"]),
        "version": int(item["version"]),
        "status": status_value,
        "dependency_status": dependency_status,
        "is_current": bool(item.get("is_current", False) and dependency_status == "current"),
        "content": content,
        "input_item_ids": input_item_ids,
        "citation_keys": citation_keys if isinstance(citation_keys, list) else [],
        "created_at": str(item.get("created_at", "")),
        "updated_at": str(item.get("updated_at", "")),
        "run_id": str(item.get("run_id", "")),
    }


def _executor(request: Request) -> ResearchExecutor:
    return cast(ResearchExecutor, request.app.state.research_executor)


def _translate_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ResearchNotFoundError):
        return HTTPException(
            status_code=404,
            detail="Research object not found",
            headers={"Cache-Control": PRIVATE_NO_STORE},
        )
    if isinstance(exc, ResearchConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    raise exc


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = PRIVATE_NO_STORE


@router.get("")
def project_list(
    response: Response,
    user: CurrentUser,
    status_filter: Literal["active", "archived"] | None = Query(default=None, alias="status"),
) -> dict[str, Any]:
    _no_store(response)
    with connect() as conn:
        return {"items": list_projects(conn, user.id, status=status_filter)}


@router.post("", status_code=status.HTTP_201_CREATED)
def project_create(payload: ProjectCreateRequest, user: CurrentUser) -> dict[str, Any]:
    with connect() as conn:
        try:
            return create_project(
                conn,
                user_id=user.id,
                title=payload.title.strip(),
                description=payload.description.strip(),
            )
        except (ResearchNotFoundError, ResearchConflictError, ValueError) as exc:
            raise _translate_error(exc) from exc


@router.get("/backlinks")
def backlinks(
    response: Response,
    user: CurrentUser,
    item_type: Literal["run", "paper", "research_report"] = Query(),
    run_id: str | None = Query(default=None, max_length=100),
    paper_id: int | None = Query(default=None, ge=1),
    artifact_id: str | None = Query(default=None, max_length=100),
    artifact_version: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    _no_store(response)
    identity = ProjectItemCreateRequest(
        item_type=item_type,
        run_id=run_id,
        paper_id=paper_id,
        artifact_id=artifact_id,
        artifact_version=artifact_version,
    )
    with connect() as conn:
        try:
            items = project_backlinks(
                conn,
                user_id=user.id,
                **identity.model_dump(),
            )
            return {
                "items": [
                    {
                        "project_id": str(item["id"]),
                        "project_title": str(item["title"]),
                        "project_status": str(item["status"]),
                        "item_id": str(item["item_id"]),
                    }
                    for item in items
                ]
            }
        except (ResearchNotFoundError, ResearchConflictError, ValueError) as exc:
            raise _translate_error(exc) from exc


@router.get("/{project_id}")
def project_detail(project_id: str, response: Response, user: CurrentUser) -> dict[str, Any]:
    _no_store(response)
    with connect() as conn:
        try:
            project = get_project(conn, project_id, user.id, include_items=True)
            project["items"] = [
                _item_dto(item, position=index)
                for index, item in enumerate(project.get("items", []))
            ]
            return project
        except ResearchNotFoundError as exc:
            raise _translate_error(exc) from exc


@router.patch("/{project_id}")
def project_update(
    project_id: str,
    payload: ProjectUpdateRequest,
    user: CurrentUser,
) -> dict[str, Any]:
    with connect() as conn:
        try:
            current = get_project(conn, project_id, user.id, include_items=False)
            return update_project(
                conn,
                project_id,
                user.id,
                title=payload.title.strip() if payload.title is not None else str(current["title"]),
                description=payload.description.strip() if payload.description is not None else str(current["description"]),
            )
        except (ResearchNotFoundError, ResearchConflictError, ValueError) as exc:
            raise _translate_error(exc) from exc


@router.delete("/{project_id}")
def project_delete(project_id: str, user: CurrentUser) -> dict[str, bool]:
    with connect() as conn:
        try:
            delete_project(conn, project_id, user.id)
        except (ResearchNotFoundError, ResearchConflictError) as exc:
            raise _translate_error(exc) from exc
    return {"deleted": True}


@router.post("/{project_id}/archive")
def project_archive(project_id: str, user: CurrentUser) -> dict[str, Any]:
    with connect() as conn:
        try:
            return set_project_status(conn, project_id, user.id, status="archived")
        except (ResearchNotFoundError, ResearchConflictError) as exc:
            raise _translate_error(exc) from exc


@router.post("/{project_id}/restore")
def project_restore(project_id: str, user: CurrentUser) -> dict[str, Any]:
    with connect() as conn:
        try:
            return set_project_status(conn, project_id, user.id, status="active")
        except (ResearchNotFoundError, ResearchConflictError) as exc:
            raise _translate_error(exc) from exc


@router.get("/{project_id}/items")
def project_items(project_id: str, response: Response, user: CurrentUser) -> dict[str, Any]:
    _no_store(response)
    with connect() as conn:
        try:
            project = get_project(conn, project_id, user.id, include_items=True)
        except ResearchNotFoundError as exc:
            raise _translate_error(exc) from exc
    return {
        "items": [_item_dto(item, position=index) for index, item in enumerate(project.get("items", []))],
        "project_revision": project.get("items_revision"),
    }


@router.post("/{project_id}/items", status_code=status.HTTP_201_CREATED)
def project_item_add(
    project_id: str,
    payload: ProjectItemCreateRequest,
    user: CurrentUser,
) -> dict[str, Any]:
    with connect() as conn:
        try:
            item = add_project_item(
                conn,
                project_id,
                user.id,
                **payload.model_dump(),
            )
            return _item_dto(item)
        except (ResearchNotFoundError, ResearchConflictError, ValueError) as exc:
            raise _translate_error(exc) from exc


@router.delete("/{project_id}/items/{item_id}")
def project_item_remove(project_id: str, item_id: str, user: CurrentUser) -> dict[str, Any]:
    with connect() as conn:
        try:
            remove_project_item(conn, project_id, user.id, item_id)
            return {"deleted": True}
        except (ResearchNotFoundError, ResearchConflictError) as exc:
            raise _translate_error(exc) from exc


@router.patch("/{project_id}/items/{item_id}")
def project_item_reposition(
    project_id: str,
    item_id: str,
    payload: ProjectItemPositionRequest,
    user: CurrentUser,
) -> dict[str, Any]:
    with connect() as conn:
        try:
            project = get_project(conn, project_id, user.id, include_items=True)
            item_ids = [str(item["id"]) for item in project.get("items", [])]
            if item_id not in item_ids:
                raise ResearchNotFoundError("project item not found")
            item_ids.remove(item_id)
            item_ids.insert(min(payload.position, len(item_ids)), item_id)
            items = reorder_project_items(conn, project_id, user.id, ordered_item_ids=item_ids)
            return {"items": [_item_dto(item, position=index) for index, item in enumerate(items)]}
        except (ResearchNotFoundError, ResearchConflictError, ValueError) as exc:
            raise _translate_error(exc) from exc


@router.post("/{project_id}/items/reorder")
def project_items_reorder(
    project_id: str,
    payload: ProjectItemReorderRequest,
    user: CurrentUser,
) -> dict[str, Any]:
    with connect() as conn:
        try:
            items = reorder_project_items(
                conn,
                project_id,
                user.id,
                ordered_item_ids=payload.item_ids,
            )
            return {
                "items": [_item_dto(item, position=index) for index, item in enumerate(items)]
            }
        except (ResearchNotFoundError, ResearchConflictError, ValueError) as exc:
            raise _translate_error(exc) from exc


@router.get("/{project_id}/coverage")
def project_coverage(project_id: str, response: Response, user: CurrentUser) -> dict[str, Any]:
    _no_store(response)
    with connect() as conn:
        try:
            validation = validate_project_inputs(conn, project_id, user.id)
            coverage = validation["coverage"]
            ready = bool(coverage.get("ready"))
            limited = (
                bool(validation.get("can_generate_limited"))
                and int(coverage.get("unique_papers", 0)) >= 1
                and not ready
            )
            warnings: list[str] = []
            if int(coverage.get("stale", 0)):
                warnings.append("部分资料已更新，需要重新加入或重新分析。")
            if int(coverage.get("inaccessible", 0)):
                warnings.append("部分资料当前不可访问，相关事实不会显示。")
            if limited:
                warnings.append("当前资料仅支持覆盖有限的研究脉络。")
            missing: list[str] = []
            if int(coverage.get("unique_papers", 0)) < 2:
                missing.append("至少需要两篇当前可访问的不同论文")
            if int(coverage.get("valid_citations", 0)) < 1:
                missing.append("至少需要一条当前有效的引用证据")
            project = get_project(conn, project_id, user.id, include_items=False)
            return {
                "status": "ready" if ready else "limited" if limited else "blocked",
                "total_items": int(coverage.get("total", 0)),
                "current_items": int(coverage.get("valid", 0)),
                "stale_items": int(coverage.get("stale", 0)),
                "inaccessible_items": int(coverage.get("inaccessible", 0)),
                "paper_count": int(coverage.get("unique_papers", coverage.get("papers", 0))),
                "report_count": int(coverage.get("reports", 0)),
                "valid_citation_count": int(coverage.get("valid_citations", 0)),
                "missing_inputs": missing,
                "warnings": warnings,
                "can_analyze": ready or limited,
                "updated_at": str(project["updated_at"]),
            }
        except ResearchNotFoundError as exc:
            raise _translate_error(exc) from exc


@router.post("/{project_id}/analysis", status_code=status.HTTP_202_ACCEPTED)
def project_analysis_start(
    project_id: str,
    request: Request,
    user: CurrentUser,
) -> dict[str, Any]:
    with connect() as conn:
        try:
            run = create_project_analysis_run(conn, project_id, user.id)
        except (ResearchNotFoundError, ResearchConflictError) as exc:
            raise _translate_error(exc) from exc
    _executor(request).wake()
    return {"project_id": project_id, "run": run, "tool_summaries": []}


@router.get("/{project_id}/analysis")
def project_analysis_get(
    project_id: str,
    response: Response,
    user: CurrentUser,
) -> dict[str, Any]:
    _no_store(response)
    with connect() as conn:
        try:
            run = get_latest_project_analysis(conn, project_id, user.id)
        except ResearchNotFoundError as exc:
            raise _translate_error(exc) from exc
    return {"project_id": project_id, "run": run, "tool_summaries": []}


@router.post("/{project_id}/analysis/{action}")
def project_analysis_control(
    project_id: str,
    action: Literal["pause", "resume", "cancel", "retry"],
    request: Request,
    user: CurrentUser,
) -> dict[str, Any]:
    with connect() as conn:
        try:
            current = get_latest_project_analysis(conn, project_id, user.id)
            if current is None:
                raise ResearchNotFoundError("project analysis run not found")
            run_id = str(current["id"])
            if action in {"pause", "cancel"}:
                run = request_action(conn, run_id, user.id, action)
            elif action == "resume":
                run = resume_run(conn, run_id, user.id)
            else:
                run = retry_run(conn, run_id, user.id)
        except (ResearchNotFoundError, ResearchConflictError) as exc:
            raise _translate_error(exc) from exc
    _executor(request).wake()
    return {"project_id": project_id, "run": run, "tool_summaries": []}


def _artifact_type(view: str) -> str:
    try:
        return VIEW_TYPES[view]
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail="Research object not found",
            headers={"Cache-Control": PRIVATE_NO_STORE},
        ) from exc


@router.get("/{project_id}/artifacts/{view}/versions")
def project_artifact_versions(
    project_id: str,
    view: str,
    response: Response,
    user: CurrentUser,
) -> dict[str, Any]:
    _no_store(response)
    with connect() as conn:
        try:
            items = list_project_artifacts(
                conn,
                project_id,
                user.id,
                artifact_type=_artifact_type(view),
            )
            return {
                "items": [
                    _artifact_dto(item)
                    for item in items
                ]
            }
        except ResearchNotFoundError as exc:
            raise _translate_error(exc) from exc


@router.get("/{project_id}/artifacts/{view}")
def project_artifact_view(
    project_id: str,
    view: str,
    response: Response,
    user: CurrentUser,
    version: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    _no_store(response)
    artifact_type = _artifact_type(view)
    with connect() as conn:
        try:
            items = list_project_artifacts(
                conn,
                project_id,
                user.id,
                artifact_type=artifact_type,
            )
        except ResearchNotFoundError as exc:
            raise _translate_error(exc) from exc
    if not items:
        raise HTTPException(
            status_code=404,
            detail="Research object not found",
            headers={"Cache-Control": PRIVATE_NO_STORE},
        )
    selected: dict[str, Any] | None
    if version is None:
        selected = max(items, key=lambda item: int(item["version"]))
    else:
        selected = next((item for item in items if int(item["version"]) == version), None)
    if selected is None:
        raise HTTPException(
            status_code=404,
            detail="Research object not found",
            headers={"Cache-Control": PRIVATE_NO_STORE},
        )
    return _artifact_dto(selected)


@router.get("/{project_id}/entities/{entity_kind}/{entity_id}/evidence")
def project_graph_entity_evidence(
    project_id: str,
    entity_kind: Literal["cluster", "timeline_event", "node", "edge"],
    entity_id: str,
    response: Response,
    user: CurrentUser,
    artifact_version: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    _no_store(response)
    with connect() as conn:
        try:
            artifact_type = {
                "cluster": "topic_clusters",
                "timeline_event": "research_timeline",
                "node": "research_graph",
                "edge": "research_graph",
            }[entity_kind]
            artifacts = list_project_artifacts(conn, project_id, user.id, artifact_type=artifact_type)
            artifact = next(
                (
                    item for item in artifacts
                    if artifact_version is None and item.get("is_current")
                    or artifact_version is not None and int(item["version"]) == artifact_version
                ),
                None,
            )
            if artifact is None or artifact.get("dependency_status") != "current":
                raise ResearchNotFoundError("research landscape entity not found")
            content = artifact.get("content")
            if not isinstance(content, dict):
                raise ResearchNotFoundError("research landscape entity not found")
            selected: Any = None
            citation_keys: list[str] = []
            if entity_kind in {"node", "edge"}:
                graph = ResearchGraph.model_validate(content)
                entities: list[ResearchGraphNode | ResearchGraphEdge] = (
                    list(graph.nodes) if entity_kind == "node" else list(graph.edges)
                )
                selected = next(
                    (
                        item for item in entities
                        if (item.node_id if isinstance(item, ResearchGraphNode) else item.edge_id) == entity_id
                    ),
                    None,
                )
                citation_keys = [] if isinstance(selected, ResearchGraphNode) else list(selected.citation_keys if selected else [])
            elif entity_kind == "cluster":
                selected = next(
                    (item for item in content.get("clusters", []) if isinstance(item, dict) and item.get("cluster_id") == entity_id),
                    None,
                )
                citation_keys = list(selected.get("citation_keys", [])) if selected else []
            else:
                selected = next(
                    (item for item in content.get("events", []) if isinstance(item, dict) and item.get("event_id") == entity_id),
                    None,
                )
                citation_keys = list(selected.get("citation_keys", [])) if selected else []
            if selected is None:
                raise ResearchNotFoundError("research landscape entity not found")
            refs = list_project_citation_refs(conn, project_id, str(artifact["run_id"]), user.id)
            refs_by_key = {
                str(ref["citation_key"]): ref
                for ref in refs
                if ref.get("status") == "valid" and ref.get("citation_key")
            }
            evidence = []
            for key in citation_keys:
                ref = refs_by_key.get(key)
                if ref is None:
                    raise ResearchNotFoundError("project citation reference not found")
                raw = get_project_citation_evidence(
                    conn,
                    project_id,
                    str(artifact["run_id"]),
                    str(ref["id"]),
                    user.id,
                )
                evidence.append(
                    {
                        "citation_id": str(ref["id"]),
                        "citation_label": key,
                        "status": raw.get("status", "stale"),
                        "paper_id": raw.get("paper_id"),
                        "paper_title": raw.get("paper_title"),
                        "heading": raw.get("heading"),
                        "excerpt": raw.get("excerpt"),
                        "chunk_id": raw.get("chunk_id"),
                        "char_start": raw.get("char_start"),
                        "char_end": raw.get("char_end"),
                    }
                )
            return {
                "entity_id": entity_id,
                "entity_kind": entity_kind,
                "dependency_status": "current",
                "citations": evidence,
            }
        except (ResearchNotFoundError, ResearchConflictError) as exc:
            raise _translate_error(exc) from exc

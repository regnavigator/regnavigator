"""직무(task) 템플릿 — 기능연계를 이름 붙여 저장·목록·이름변경·삭제 (2026-10-06).

LLM 호출 없음(쿼터 밖). 전부 user 스코프. 동기 repo 라 `def` 라우트(스레드풀).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from src.persistence import get_task_templates_repo
from src.persistence.task_templates_repo import MAX_NAME_LEN, MAX_PER_USER, strip_for_template
from src.workflow import MAX_STEPS

router = APIRouter()


def _require_user(request: Request) -> str:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return str(user_id)


def _name(v) -> str:
    name = str(v or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="이름을 적어 주세요")
    if len(name) > MAX_NAME_LEN:
        raise HTTPException(status_code=422, detail=f"이름은 {MAX_NAME_LEN}자까지입니다")
    return name


@router.post("/task-templates", status_code=201)
async def create_task_template(request: Request):
    """body: `{"name": str, "steps": [{"fn": str, "confidential"?: bool, …}]}` — 값·파일은 버린다."""
    user_id = _require_user(request)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="body must be JSON object")
    name = _name(body.get("name"))
    steps = strip_for_template(body.get("steps") if isinstance(body.get("steps"), list) else [])
    if not steps:
        raise HTTPException(status_code=422, detail="저장할 단계가 없습니다")
    if len(steps) > MAX_STEPS:
        raise HTTPException(status_code=422, detail=f"직무는 최대 {MAX_STEPS}단계까지입니다")
    repo = get_task_templates_repo()
    if repo.count_for_user(user_id) >= MAX_PER_USER:
        raise HTTPException(status_code=422, detail=f"직무는 {MAX_PER_USER}개까지 저장할 수 있습니다")
    return repo.create(user_id, name, steps).as_dict()


@router.get("/task-templates")
def list_task_templates(request: Request):
    user_id = _require_user(request)
    return {"items": [t.as_dict() for t in get_task_templates_repo().list_for_user(user_id)]}


@router.patch("/task-templates/{template_id}")
async def rename_task_template(template_id: str, request: Request):
    user_id = _require_user(request)
    body = await request.json()
    name = _name(body.get("name") if isinstance(body, dict) else None)
    if not get_task_templates_repo().rename(user_id, template_id, name):
        raise HTTPException(status_code=404, detail="직무를 찾을 수 없습니다")
    return {"ok": True, "name": name}


@router.delete("/task-templates/{template_id}", status_code=204)
def delete_task_template(template_id: str, request: Request):
    user_id = _require_user(request)
    if not get_task_templates_repo().delete(user_id, template_id):
        raise HTTPException(status_code=404, detail="직무를 찾을 수 없습니다")
    return None

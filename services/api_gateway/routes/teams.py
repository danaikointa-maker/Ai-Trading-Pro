from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.api_gateway.accounts import AccountError, add_team_member, create_team, list_teams, remove_team_member
from services.api_gateway.deps import Runtime, current_user, require_admin
from services.api_gateway.state import TradingRuntime

router = APIRouter(prefix="/api/teams", tags=["teams"])


class CreateTeamRequest(BaseModel):
    name: str


class TeamMemberRequest(BaseModel):
    email: str
    team_role: str = "member"


@router.get("")
def get_teams(runtime: TradingRuntime = Runtime, user=Depends(current_user)):
    return {"teams": list_teams(runtime.db, user["tenant_id"], user["email"],
                                is_admin=user.get("role") == "admin",
                                can_assign=user.get("role") in {"admin", "trader"})}


@router.post("")
def post_team(payload: CreateTeamRequest, runtime: TradingRuntime = Runtime,
              user=Depends(require_admin)):
    try:
        team = create_team(runtime.db, user["tenant_id"], payload.name, user["email"])
    except AccountError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    runtime.db.audit(user["email"], "teams.create", {"team_id": team["id"], "name": team["name"]})
    return team


@router.post("/{team_id}/members")
def post_member(team_id: str, payload: TeamMemberRequest,
                runtime: TradingRuntime = Runtime, user=Depends(require_admin)):
    try:
        member = add_team_member(runtime.db, user["tenant_id"], team_id,
                                 payload.email, payload.team_role)
    except AccountError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    runtime.db.audit(user["email"], "teams.member.add", member)
    return member


@router.delete("/{team_id}/members/{email}")
def delete_member(team_id: str, email: str,
                  runtime: TradingRuntime = Runtime, user=Depends(require_admin)):
    try:
        remove_team_member(runtime.db, user["tenant_id"], team_id, email)
    except AccountError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    runtime.db.audit(user["email"], "teams.member.remove", {"team_id": team_id, "email": email.lower()})
    return {"ok": True}
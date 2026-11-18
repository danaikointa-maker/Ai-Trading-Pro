"""Offline, read-only contract for the No7 AI Dev Team project registry.

This module deliberately does not make network calls or accept credentials. The
upstream OIDC identity and tenant/project IDs are not provisioned yet.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

UPSTREAM_REPOSITORY = "danaikointa-maker/no7_ai_dev_team_plan"
UPSTREAM_CONTRACT_COMMIT = "cb1ccaf6dd9fd999d82629d6e0f25748134c03d6"
UPSTREAM_PROJECTS_ENDPOINT = "/api/v1/projects"
SAMPLE_FIXTURE = Path(__file__).with_name("fixtures") / "project_snapshot.sample.json"


class DevTeamProject(BaseModel):
    """The read-only ProjectRead shape exposed by No7 AI Dev Team's registry."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    tenant_id: UUID
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(max_length=4000)
    repository_url: str | None = Field(default=None, max_length=2048)
    status: Literal["registered", "active", "archived"]
    created_at: datetime
    updated_at: datetime
    role: Literal["owner", "developer", "reviewer", "viewer", "super_admin"] | None

    @field_validator("name")
    @classmethod
    def non_blank_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("project name cannot be blank")
        return value

    @field_validator("repository_url")
    @classmethod
    def require_safe_https_repository_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("repository_url must be an HTTPS URL without credentials, query, or fragment")
        return value


class DevTeamProjectSnapshot(BaseModel):
    """A scoped snapshot with explicit provenance and execution permanently disabled."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["no7-ai-dev-team.project-snapshot.v1"]
    source: Literal["fixture", "api"]
    observed_at: datetime
    scope_tenant_id: UUID
    upstream_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    execution_enabled: Literal[False]
    projects: list[DevTeamProject] = Field(max_length=200)

    @field_validator("observed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return value

    @model_validator(mode="after")
    def enforce_tenant_scope(self) -> DevTeamProjectSnapshot:
        if any(project.tenant_id != self.scope_tenant_id for project in self.projects):
            raise ValueError("snapshot contains a project outside scope_tenant_id")
        return self


def parse_project_list(payload: Any, *, tenant_id: UUID) -> list[DevTeamProject]:
    """Validate one tenant-scoped GET /api/v1/projects response; never mutates data."""
    if not isinstance(payload, list):
        raise ValueError("project registry response must be a JSON array")
    if len(payload) > 200:
        raise ValueError("project registry response exceeds the API page limit")
    projects = [DevTeamProject.model_validate(item) for item in payload]
    if any(project.tenant_id != tenant_id for project in projects):
        raise ValueError("project registry response escaped the requested tenant scope")
    return projects


def load_sample_fixture() -> DevTeamProjectSnapshot:
    """Load the checked-in sample from this package; callers cannot choose a file path."""
    payload = json.loads(SAMPLE_FIXTURE.read_text(encoding="utf-8"))
    return DevTeamProjectSnapshot.model_validate(payload)

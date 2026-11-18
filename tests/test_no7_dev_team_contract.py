from copy import deepcopy
from uuid import UUID

import pytest
from pydantic import ValidationError

from integrations.no7_dev_team.contracts import (
    DevTeamProjectSnapshot,
    load_sample_fixture,
    parse_project_list,
    select_scoped_project,
)


def test_sample_fixture_is_explicitly_offline_and_non_executable():
    snapshot = load_sample_fixture()

    assert snapshot.source == "fixture"
    assert snapshot.execution_enabled is False
    assert len(snapshot.projects) == 1
    assert snapshot.projects[0].status == "registered"
    assert "Sample only" in snapshot.projects[0].name


def test_project_list_must_stay_inside_requested_tenant():
    fixture = load_sample_fixture()
    project = fixture.projects[0].model_dump(mode="json")
    project["tenant_id"] = "00000000-0000-4000-8000-000000000003"

    with pytest.raises(ValueError, match="escaped the requested tenant scope"):
        parse_project_list([project], tenant_id=fixture.scope_tenant_id)


def test_project_selection_requires_the_exact_tenant_and_project_ids():
    fixture = load_sample_fixture()
    project = select_scoped_project(
        fixture.projects,
        tenant_id=fixture.scope_tenant_id,
        project_id=fixture.projects[0].id,
    )

    assert project.id == fixture.projects[0].id
    with pytest.raises(ValueError, match="missing or ambiguous"):
        select_scoped_project(
            fixture.projects,
            tenant_id=fixture.scope_tenant_id,
            project_id=UUID("00000000-0000-4000-8000-000000000009"),
        )
    with pytest.raises(ValueError, match="required UUIDs"):
        select_scoped_project(fixture.projects, tenant_id=None, project_id=None)


def test_project_selection_rejects_duplicate_matching_rows():
    fixture = load_sample_fixture()
    with pytest.raises(ValueError, match="missing or ambiguous"):
        select_scoped_project(
            [fixture.projects[0], fixture.projects[0]],
            tenant_id=fixture.scope_tenant_id,
            project_id=fixture.projects[0].id,
        )


def test_project_contract_rejects_unknown_fields_and_write_capabilities():
    fixture = load_sample_fixture().model_dump(mode="json")
    with_access_token = deepcopy(fixture)
    with_access_token["access_token"] = "must-not-be-carried"
    with pytest.raises(ValidationError):
        DevTeamProjectSnapshot.model_validate(with_access_token)

    with_execution_enabled = deepcopy(fixture)
    with_execution_enabled["execution_enabled"] = True
    with pytest.raises(ValidationError):
        DevTeamProjectSnapshot.model_validate(with_execution_enabled)


def test_project_contract_rejects_unsafe_repository_url():
    fixture = load_sample_fixture().model_dump(mode="json")
    fixture["projects"][0]["repository_url"] = "https://user:password@example.invalid/repo"

    with pytest.raises(ValidationError, match="repository_url"):
        DevTeamProjectSnapshot.model_validate(fixture)


def test_project_contract_rejects_timezone_free_observation_time():
    fixture = load_sample_fixture().model_dump(mode="json")
    fixture["observed_at"] = "2026-11-18T00:00:00"

    with pytest.raises(ValidationError, match="observed_at"):
        DevTeamProjectSnapshot.model_validate(fixture)


def test_contract_uses_uuid_tenant_scope():
    fixture = load_sample_fixture()
    assert isinstance(fixture.scope_tenant_id, UUID)

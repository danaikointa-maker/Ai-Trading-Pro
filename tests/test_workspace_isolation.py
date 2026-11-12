from types import SimpleNamespace

import pytest

from packages.persistence.db import Database


def test_database_cannot_be_relabelled_as_another_workspace(tmp_path):
    path = str(tmp_path / "workspace.sqlite3")
    db = Database(path, workspace_id="team-a")
    db.close()
    reopened = Database(path, workspace_id="team-a")
    reopened.close()
    with pytest.raises(ValueError, match="workspace"):
        Database(path, workspace_id="team-b")


@pytest.mark.parametrize("workspace", ["", "../other", "a b", "a" * 65])
def test_invalid_workspace_identity_refused(tmp_path, workspace):
    with pytest.raises(ValueError, match="workspace"):
        Database(str(tmp_path / "invalid.sqlite3"), workspace_id=workspace)


def test_token_cannot_cross_workspace_with_same_secret():
    from services.api_gateway.auth import create_token, decode_token

    def settings(workspace):
        return SimpleNamespace(security={"jwt_secret": "test-only-shared-secret-32bytes-long",
                                         "workspace_id": workspace})
    token, _ = create_token(settings("team-a"), "same@example.com")
    assert decode_token(settings("team-a"), token)
    assert decode_token(settings("team-b"), token) is None


def test_cluster_frames_have_workspace_specific_namespaces(settings, monkeypatch):
    monkeypatch.setenv("NO7_WORKSPACE_ID", "team-a")
    first = settings.cluster["key_prefix"]
    monkeypatch.setenv("NO7_WORKSPACE_ID", "team-b")
    second = settings.cluster["key_prefix"]
    assert first != second
    assert first.endswith(":workspace:team-a")


def test_legacy_workspace_token_is_not_accepted():
    import time
    import jwt
    from services.api_gateway.auth import decode_token

    settings = SimpleNamespace(security={"jwt_secret": "test-only-shared-secret-32bytes-long"})
    token = jwt.encode({"sub": "same@example.com", "exp": time.time() + 60,
                        "iss": "no7-ai-trading-pro"}, settings.security["jwt_secret"], algorithm="HS256")
    assert decode_token(settings, token) is None
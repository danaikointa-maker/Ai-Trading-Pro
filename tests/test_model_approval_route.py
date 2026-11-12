"""Approval API must preserve registry refusal rather than claim success."""
from types import SimpleNamespace
from threading import RLock
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from services.api_gateway.routes.analysis import approve


@pytest.mark.parametrize('approved', [True, False])
def test_registry_refusal_is_not_reported_as_success(approved):
    runtime = SimpleNamespace(model_registry=Mock(), predictor=Mock(), lock=RLock(), forecasts={})
    runtime.model_registry.approve.return_value = False
    with pytest.raises(HTTPException) as exc:
        approve('missing', {'approved': approved}, runtime, {'email': 'researcher'})
    assert exc.value.status_code == 409
    assert exc.value.detail == 'Model approval change refused; verify registration and artifact integrity.'
    runtime.predictor.load_latest.assert_not_called()


@pytest.mark.parametrize('approved', [True, False])
def test_successful_registry_change_retains_response_contract(approved):
    runtime = SimpleNamespace(model_registry=Mock(), predictor=Mock(), lock=RLock(), forecasts={})
    runtime.model_registry.approve.return_value = True
    result = approve('owned', {'approved': approved}, runtime, {'email': 'researcher'})
    assert result['ok'] is True
    assert result['approved'] is approved
    runtime.model_registry.approve.assert_called_once_with('owned', approved)
    runtime.predictor.load_latest.assert_called_once_with()
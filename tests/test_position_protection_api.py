def test_v1_1_protection_routes_are_included_and_auto_stays_locked(client, auth):
    state = client.get("/api/position-protection", headers=auth)
    assert state.status_code == 200, state.text
    payload = state.json()
    assert payload["profile"]["id"] == "position-protection-v1.1"
    assert payload["profile"]["status"] == "staged"
    assert payload["execution"] == "paper"
    assert payload["live_auto_enabled"] is False

    locked = client.put("/api/position-protection/mode", headers=auth,
                        json={"mode": "FULL_AUTO"})
    assert locked.status_code == 403


def test_protection_preview_rejects_unknown_position_without_mutation(client, auth):
    before = client.get("/api/position-protection", headers=auth).json()
    response = client.post("/api/position-protection/preview", headers=auth,
                           json={"ticket": "not-open", "action": "break_even", "mode": "MANUAL"})
    assert response.status_code == 404
    after = client.get("/api/position-protection", headers=auth).json()
    assert after["positions"] == before["positions"]
    assert after["live_auto_enabled"] is False

import pytest

from services.api_gateway.routes.market import quote_freshness


@pytest.mark.parametrize("tick_time,issue", [(999, None), (960, "stale_quote"),
                                            (8200, "future_timestamp")])
def test_quote_clock_cannot_certify_old_or_future_prices(tick_time, issue):
    result = quote_freshness(tick_time, now=1000)
    assert result["clock_issue"] == issue
    assert result["stale"] == (issue is not None)
    assert result["quote_age_seconds"] == 1000 - tick_time

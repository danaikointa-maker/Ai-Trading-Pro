"""Source-contract checks only; MetaEditor compile and terminal crash tests are separate gates."""
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / 'bridge' / 'No7BridgeEA.mq5'


def test_ea_claims_durably_before_execution():
    source = SOURCE.read_text(encoding='utf-8')
    assert 'bool ClaimCommand(const string id)' in source
    assert 'FILE_COMMON' in source
    assert 'FileFlush(g_journal)' in source
    assert 'if(!ClaimCommand(id))' in source
    claim = source.index('if(!ClaimCommand(id))')
    execute = source.index('string outcome = ExecuteCommand(kind, object);')
    assert claim < execute
    assert 'ArrayResize(g_executed_ids, 199)' not in source


def test_ea_replays_durable_results_without_resending():
    source = SOURCE.read_text(encoding='utf-8')
    assert 'bool LoadCommandJournal()' in source
    assert 'bool SaveCommandOutcome(' in source
    assert 'AppendResult(id, g_executed_results[known])' in source
    assert 'manual reconciliation required' in source


def test_ea_reports_profit_currency_for_contract_completeness():
    source = SOURCE.read_text(encoding='utf-8')
    assert 'SYMBOL_CURRENCY_PROFIT' in source
    assert 'profit_currency' in source


def test_ea_short_write_and_read_errors_fail_closed():
    source = SOURCE.read_text(encoding='utf-8')
    assert 'written != expected_bytes' in source
    assert 'if(GetLastError() != 0)' in source
    assert 'g_executed_outcomes[index]' in source


def test_ea_close_receipt_uses_result_volume_and_distinguishes_partial():
    source = SOURCE.read_text(encoding='utf-8')
    close = source.split('string DoClose(', 1)[1].split('string DoModify(', 1)[0]
    assert 'TRADE_RETCODE_DONE_PARTIAL' in close
    assert 'partially_filled' in close
    assert 'result.volume' in close
    assert 'result.price, request.volume' not in close
    assert 'close acknowledgement' in close
    assert 'closed %I64u' not in close
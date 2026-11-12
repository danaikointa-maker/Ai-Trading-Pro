@echo off
setlocal
"C:\workspace\Ai-Trading-Pro\.venv\Scripts\python.exe" "C:\workspace\Ai-Trading-Pro\storage\local-dev\qa\safety\run_durable_pytest.py" "C:\workspace\Ai-Trading-Pro\storage\local-dev\qa\safety\p25-durable-batch-02" 900 "tests/test_backtest_engine.py" "tests/test_backtest_tick_refusal.py" "tests/test_bridge.py" "tests/test_bridge_readonly.py"
exit /b %ERRORLEVEL%
"""Real stdio negotiation and calls; no model, broker or HTTP server."""
import asyncio
from importlib.util import find_spec
import os
import subprocess
import sys

import pytest

from feedback_helpers import ROOT, AFTER_HORIZON, decision, feedback_project

requires_mcp = pytest.mark.skipif(find_spec("mcp") is None, reason="Optional MCP SDK not installed")


@requires_mcp
def test_real_stdio_protocol_retries_and_safe_errors(feedback_project, tmp_path):
    from mcp import Client, StdioServerParameters
    async def check():
        params = StdioServerParameters(command=sys.executable,
            args=["-m", "tradeoff", "feedback", "mcp", "--project", str(feedback_project)],
            env={"PYTHONPATH": str(ROOT / "src")})
        log_path = tmp_path / "stderr.log"
        with log_path.open("w") as log:
            # SDK accepts a file for server stderr through its stdio transport.
            from mcp.client.stdio import stdio_client
            from mcp.client import ClientSession
            async with stdio_client(params, errlog=log) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    listing = await session.list_tools()
                    assert len(listing.tools) == 10
                    assert "tradeoff_record_decision" in {t.name for t in listing.tools}
                    first = await session.call_tool("tradeoff_record_decision", {"event_id": "mcp-d1", "decision": decision()})
                    assert not first.is_error
                    assert first.structured_content["event_id"] == "mcp-d1"
                    again = await session.call_tool("tradeoff_record_decision", {"event_id": "mcp-d1", "decision": decision()})
                    assert again.structured_content == first.structured_content
                    for name, args in [("tradeoff_record_decision", {"api_key": "SYNTHETIC_SECRET_SENTINEL"}),
                        ("tradeoff_export_feedback", {"output": "../escape", "as_of": AFTER_HORIZON}),
                        ("tradeoff_evaluate_decisions", {"as_of": AFTER_HORIZON, "unknown": "SYNTHETIC_SECRET_SENTINEL"}),
                        ("tradeoff_evaluate_decisions", {"as_of": "x" * (1024*1024+1)})]:
                        result = await session.call_tool(name, args)
                        assert result.is_error
                        assert "SYNTHETIC_SECRET_SENTINEL" not in str(result)
                        assert str(feedback_project) not in str(result)
                    result = await session.call_tool("tradeoff_evaluate_decisions", {"as_of": AFTER_HORIZON})
                    assert not result.is_error
                    assert result.structured_content["evaluation"]["coverage"]["decision_count"] == 1
                    (feedback_project / 'prices.csv').write_text('timestamp,price,received\n2026-01-05T15:30:00Z,12,2026-01-05T15:30:01Z\n')
                    configured = await session.call_tool('tradeoff_configure_price_source', dict(data_file='prices.csv',symbol='SYNTH',
                        currency='USD',source='fixture',feed='fixture-feed',price_kind='mid',available_at_column='received'))
                    assert not configured.is_error
                    collected = await session.call_tool('tradeoff_collect_outcomes', {'as_of':AFTER_HORIZON})
                    assert not collected.is_error
                    assert collected.structured_content['collection']['new_marks'] == 1
                    assert collected.structured_content['feedback']['evaluation']['decisions'][0]['outcome_status'] == 'AVAILABLE'
        assert "SYNTHETIC_SECRET_SENTINEL" not in log_path.read_text()
    asyncio.run(check())


@requires_mcp
def test_client_convenience_negotiates(feedback_project):
    from mcp import Client, StdioServerParameters
    async def check():
        params = StdioServerParameters(command=sys.executable,
            args=["-m", "tradeoff", "feedback", "mcp", "--project", str(feedback_project)],
            env={"PYTHONPATH": str(ROOT / "src")})
        async with Client(params) as client:
            listing = await client.list_tools()
            assert "tradeoff_compare_versions" in {t.name for t in listing.tools}
    asyncio.run(check())


def test_core_import_does_not_load_mcp_sdk():
    result = subprocess.run([sys.executable, "-c", "import tradeoff.feedback.mcp, backtest_witness, sys; assert 'mcp' not in sys.modules"],
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

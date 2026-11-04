"""Isolated installed-package probe, launched only by local onboarding."""
from datetime import datetime, timedelta, timezone
from importlib.metadata import version
import json
import os
from pathlib import Path
import sys
import tempfile


def inspect_install():
    try:
        from mcp import Client, StdioServerParameters
        from mcp.client import ClientSession
        if version('mcp') != '2.3.0':
            return dict(status='FAIL', code='MCP_VERSION_MISMATCH')
    except ImportError:
        return dict(status='FAIL', code='MCP_NOT_INSTALLED')
    return dict(status='PASS', code='INSTALL_VERIFIED')


def self_test():
    import asyncio
    from mcp import StdioServerParameters
    from mcp.client import ClientSession
    from mcp.client.stdio import stdio_client
    from .api import operation_definitions
    from .contracts import utc_time
    from .recorder import Recorder
    from .store import FeedbackStore

    with tempfile.TemporaryDirectory(prefix='tradeoff-self-test-') as temporary:
        # Resolve our own temp directory (macOS /var alias), never a user workspace.
        project = Path(temporary).resolve()
        with FeedbackStore(project, create=True, environment='simulated'):
            pass
        now = datetime.now(timezone.utc)
        intent = dict(decision_id='setup-decision', agent_id='setup-agent', agent_version='self-test',
            opportunity_id='setup-opportunity', symbol='SYNTH', asset_class='us_equity', currency='USD',
            action='buy', quantity_delta='0.5', episode_id='setup-episode', input_hash='a' * 64,
            decision_at=utc_time(now), horizon_end=utc_time(now + timedelta(minutes=5)),
            reference=dict(price='10', price_kind='mid', observed_at=utc_time(now), available_at=utc_time(now),
                           source='setup-fixture', feed='setup-fixture', max_age_seconds=60))
        recorder = Recorder(project)
        receipt = recorder.record_decision(intent, event_id='setup-record')
        binding = dict(decision_id='setup-decision', source_alias='synthetic', order_id='setup-order')
        bound = recorder.bind_order(binding, event_id='setup-bind')

        async def protocol():
            params = StdioServerParameters(command=sys.executable,
                args=['-I', '-m', 'tradeoff', 'feedback', 'mcp', '--project', str(project)], env=dict(os.environ))
            with open(os.devnull, 'w') as log:
                async with stdio_client(params, errlog=log) as (reader, writer):
                    async with ClientSession(reader, writer) as session:
                        await session.initialize()
                        listing = await session.list_tools()
                        expected = {'tradeoff_' + d['operation'] for d in operation_definitions()}
                        assert {t.name for t in listing.tools} == expected
                        for tool, args, previous in [
                            ('tradeoff_record_decision', dict(event_id='setup-record', decision=intent), receipt),
                            ('tradeoff_bind_order', dict(event_id='setup-bind', binding=binding), bound)]:
                            result = await session.call_tool(tool, args)
                            assert not result.is_error
                            assert all(result.structured_content[k] == v for k, v in previous.items())
                        result = await session.call_tool('tradeoff_evaluate_decisions', dict(as_of=utc_time(datetime.now(timezone.utc))))
                        assert not result.is_error
                        assert result.structured_content['quality']['decision_count'] == 1
                        return len(expected)
        count = asyncio.run(protocol())
    return dict(status='PASS', code='SELF_TEST_VERIFIED', tools=count,
                scope='Isolated synthetic Python recording, binding, retries and real MCP calls; no real agent hook or broker tested')


def main():
    try:
        result = inspect_install()
        if result['status'] == 'PASS' and '--self-test' in sys.argv[1:]:
            result = self_test()
    except Exception:
        result = dict(status='FAIL', code='PROBE_FAILED')
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())

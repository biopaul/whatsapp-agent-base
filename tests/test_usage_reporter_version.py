"""Tests para verificar que el payload incluye version."""

import pytest
from unittest.mock import patch


@pytest.mark.asyncio
async def test_payload_includes_version():
    """El payload sent a /usage incluye el campo version."""
    from agent import __version__
    from agent import usage_reporter

    usage_reporter.USAGE_URL = 'http://test.local/usage'
    usage_reporter._bad_token = False

    captured = {}

    async def fake_post(self, url, json=None, **kwargs):
        captured['payload'] = json
        return type('R', (), {'status_code': 200, 'text': 'ok', 'content': b'ok', 'json': lambda self=None: {'inserted': 0}})()

    with patch('httpx.AsyncClient.post', new=fake_post):
        await usage_reporter._send_with_retry([{'type': 'message', 'chat_id': '123', 'at': 0}])

    assert 'version' in captured.get('payload', {}), 'payload must include version field'
    assert captured['payload']['version'] == __version__


@pytest.mark.asyncio
async def test_report_version_only_sends_payload_with_no_events():
    """report_version_only envía solo version + events vacíos."""
    from agent import __version__
    from agent import usage_reporter

    usage_reporter.USAGE_URL = 'http://test.local/usage'
    usage_reporter._bad_token = False

    captured = {}

    async def fake_post(self, url, json=None, **kwargs):
        captured['payload'] = json
        return type('R', (), {'status_code': 200, 'text': 'ok', 'content': b'ok', 'json': lambda self=None: {'inserted': 0}})()

    with patch('httpx.AsyncClient.post', new=fake_post):
        await usage_reporter.report_version_only()

    payload = captured.get('payload', {})
    assert payload.get('version') == __version__
    assert payload.get('events') == []

"""Release delivery tests use a fake Telegram API; no secrets or network required."""
import io
import json
import urllib.error

import pytest

from scripts import send_release_telegram as delivery


@pytest.fixture
def config(monkeypatch, tmp_path):
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'test-token')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', 'test-chat')
    apk = tmp_path / 'app.apk'
    apk.write_bytes(b'APK_BYTES')
    return apk


def test_uploads_document_and_version(config, monkeypatch, capsys):
    captured = {}
    def fake_open(req, timeout):
        captured['request'] = req
        assert timeout == 120
        return io.BytesIO(json.dumps({'ok': True}).encode())
    monkeypatch.setattr(delivery.urllib.request, 'urlopen', fake_open)
    delivery.send(config, '1.8.8', 'https://github.com/example/project/releases/tag/app-v1.8.8')
    req = captured['request']
    assert req.full_url.endswith('/sendDocument')
    assert b'filename="PlayReport.apk"' in req.data
    assert b'APK_BYTES' in req.data and b'1.8.8' in req.data and b'test-chat' in req.data
    assert 'test-token' not in capsys.readouterr().out


def test_missing_secrets_fail_without_request(config, monkeypatch):
    monkeypatch.delenv('TELEGRAM_CHAT_ID')
    monkeypatch.setattr(delivery.urllib.request, 'urlopen', lambda *_a, **_kw: pytest.fail('network request'))
    with pytest.raises(RuntimeError, match='requires TELEGRAM_BOT_TOKEN'):
        delivery.send(config, '1.8.8', 'https://example.test')


def test_telegram_rejection_fails_without_leaking_credentials(config, monkeypatch):
    def fail(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 403, 'Forbidden', {}, None)
    monkeypatch.setattr(delivery.urllib.request, 'urlopen', fail)
    with pytest.raises(RuntimeError, match='HTTP 403') as error:
        delivery.send(config, '1.8.8', 'https://example.test')
    assert 'test-token' not in str(error.value) and 'test-chat' not in str(error.value)


def test_unconfirmed_delivery_fails(config, monkeypatch):
    monkeypatch.setattr(delivery.urllib.request, 'urlopen', lambda *a, **kw: io.BytesIO(b'{"ok":false}'))
    with pytest.raises(RuntimeError, match='did not confirm'):
        delivery.send(config, '1.8.8', 'https://example.test')


def test_large_apk_is_not_uploaded(config, monkeypatch):
    monkeypatch.setattr(delivery, 'MAX_BYTES', 2)
    with pytest.raises(RuntimeError, match='50 MB'):
        delivery.send(config, '1.8.8', 'https://example.test')

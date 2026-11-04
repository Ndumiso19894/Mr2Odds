"""Upload an already published Android APK to the configured Telegram chat.

The existing scan workflow uses the same TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
repository secrets. No credentials or chat identifiers are printed or persisted.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

# Telegram's hosted Bot API accepts documents up to 50 MB.
MAX_BYTES = 50 * 1024 * 1024


def send(apk: Path, version: str) -> None:
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
    if not token or not chat_id:
        raise RuntimeError('Telegram delivery requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID repository secrets.')
    if not apk.is_file() or not 0 < apk.stat().st_size <= MAX_BYTES:
        raise RuntimeError('APK is missing, empty, or larger than Telegram’s 50 MB document limit.')
    boundary = 'mr2odds-' + uuid.uuid4().hex
    caption = f'Mr 2 Odds {version} for Android\n\nInstall the attached APK.'
    parts = []
    for name, value in [('chat_id', chat_id), ('caption', caption)]:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="PlayReport.apk"\r\n'
                  'Content-Type: application/vnd.android.package-archive\r\n\r\n').encode())
    parts.append(apk.read_bytes())
    parts.append(f'\r\n--{boundary}--\r\n'.encode())
    req = urllib.request.Request(f'https://api.telegram.org/bot{token}/sendDocument', data=b''.join(parts),
                                 headers={'Content-Type': f'multipart/form-data; boundary={boundary}'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        # Never log the request URL, response body, token or chat id.
        raise RuntimeError(f'Telegram rejected the upload (HTTP {exc.code}). Check bot and chat permissions.') from None
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        raise RuntimeError('Telegram upload failed. Check network access and retry the failed delivery job.') from None
    if not isinstance(result, dict) or result.get('ok') is not True:
        raise RuntimeError('Telegram did not confirm delivery. Check bot and chat permissions.')
    print('Telegram confirmed APK delivery.')


def main() -> int:
    if len(sys.argv) != 3:
        print('Usage: send_release_telegram.py APK VERSION', file=sys.stderr)
        return 2
    try:
        send(Path(sys.argv[1]), sys.argv[2])
    except RuntimeError as exc:
        print(f'::error::{exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

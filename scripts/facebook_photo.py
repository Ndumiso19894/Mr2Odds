#!/usr/bin/env python3
"""Publish the daily A4 slips image to the configured Facebook Page."""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

API = "https://graph.facebook.com/v24.0"
SAST = ZoneInfo("Africa/Johannesburg")


def credentials():
    token = os.environ.get("FACEBOOK_PAGE_ACCESS_TOKEN", "").strip()
    page_id = os.environ.get("FACEBOOK_PAGE_ID", "").strip()
    if not token or not re.fullmatch(r"\d+", page_id):
        raise ValueError("FACEBOOK_PAGE_ACCESS_TOKEN and numeric FACEBOOK_PAGE_ID must be configured")
    return token, page_id


def safe_error(response):
    try:
        error = response.json().get("error", {})
        parts = [f"HTTP {response.status_code}"]
        if isinstance(error.get("code"), int):
            parts.append(f"Facebook code {error['code']}")
        if isinstance(error.get("error_subcode"), int):
            parts.append(f"subcode {error['error_subcode']}")
        return ", ".join(parts)
    except (ValueError, TypeError, AttributeError):
        return f"HTTP {response.status_code}"


def page_token(session, token, page_id):
    headers = {"Authorization": "Bearer " + token}
    try:
        me = session.get(f"{API}/me", params={"fields": "id"}, headers=headers, timeout=30)
        if not me.ok:
            raise RuntimeError("Facebook token check rejected: " + safe_error(me))
        identity = str(me.json().get("id", ""))
        if identity == page_id:
            return token

        params = {"fields": "id,access_token", "limit": 100}
        for _ in range(10):
            response = session.get(f"{API}/me/accounts", params=params, headers=headers, timeout=30)
            if not response.ok:
                raise RuntimeError("Facebook Page access check rejected: " + safe_error(response))
            body = response.json()
            for item in body.get("data", []):
                if isinstance(item, dict) and str(item.get("id", "")) == page_id:
                    value = item.get("access_token")
                    if isinstance(value, str) and value.strip():
                        return value.strip()
                    raise RuntimeError("Facebook did not return a Page access token")
            paging = body.get("paging") or {}
            after = (paging.get("cursors") or {}).get("after") if paging.get("next") else None
            if not after:
                break
            params = {"fields": "id,access_token", "limit": 100, "after": after}
        raise RuntimeError("The configured Page is not accessible with the saved token")
    except requests.RequestException:
        raise RuntimeError("Could not reach Facebook for the Page access check") from None


def diagnose():
    token, page_id = credentials()
    page_token(requests.Session(), token, page_id)
    print("Facebook confirmed access to the configured Page.")


def publish(image_path: Path):
    token, page_id = credentials()
    if not image_path.is_file() or image_path.stat().st_size == 0:
        raise ValueError("The combined A4 image is missing or empty")
    session = requests.Session()
    token = page_token(session, token, page_id)
    from scripts.social_caption import social_caption
    caption = social_caption()
    try:
        with image_path.open("rb") as image:
            response = session.post(
                f"{API}/{page_id}/photos",
                data={"access_token": token, "message": caption},
                files={"source": ("mr2odds-daily-slips-a4.png", image, "image/png")},
                timeout=90,
            )
        if not response.ok:
            raise RuntimeError("Facebook rejected the A4 image: " + safe_error(response))
        if not response.json().get("id"):
            raise RuntimeError("Facebook did not confirm the photo ID; check the Page before retrying")
    except requests.RequestException:
        raise RuntimeError("Facebook upload result is unknown; check the Page before retrying") from None
    print("Facebook confirmed the combined A4 slip image post.")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("diagnose")
    post = sub.add_parser("publish")
    post.add_argument("--image", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "diagnose":
        diagnose()
    else:
        publish(args.image)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

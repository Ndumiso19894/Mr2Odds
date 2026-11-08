# Point-in-time snapshots (offline research prototype)

This standalone module records exact bytes supplied by a callback, local UTC timing, declared source context, and optionally event/market/outcome/price observations extracted using explicit JSON pointers. It does **not** fetch anything, run on a schedule, integrate with the scanner or backtest, or select bets. Tests use synthetic data only. No provider adapter is authorized or enabled.

## Offline example

Run from the repository root with Python 3.10+; this writes only to an automatically removed temporary directory. All data below are invented.

```python
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from research.point_in_time.snapshots import capture, load_as_of

payload = b'''{"events":[{"id":"e1","markets":[{"id":"m1","outcomes":[{"name":"Over","odds":1.1599,"active":false}]}]}]}'''
specs = [{
    "event_pointer": "/events/0", "event_id_pointer": "/id",
    "quotes": [{
        "market_pointer": "/markets/0", "market_id_pointer": "/id",
        "outcome_pointer": "/outcomes/0", "outcome_name_pointer": "/name",
        "odds_pointer": "/odds", "outcome_status_pointer": "/active",
    }],
}]
with TemporaryDirectory() as temp:
    path = capture(Path(temp), lambda: payload, provider="example", dataset="feed",
                   request_path="/events", origin="synthetic",
                   source_timezone=None, requested_offset_minutes=None,
                   event_specs=specs)
    result = load_as_of(path, datetime.now(timezone.utc), allow_non_provider=True)
    assert result["payload"] == payload
    assert result["claims"]["events"][0]["quotes"][0]["decimal_odds"] == "1.1599"
    assert result["claims"]["events"][0]["quotes"][0]["outcome_status"] is False
    print(result["receipt_sha256"])
```

`allow_non_provider=True` is **only for research inspection**; synthetic and file-import snapshots are rejected by default. Setting `origin="provider_response"` is merely a caller assertion, not evidence that the callback fetched a provider or that the provider response was authentic. This example should never be used as a price for a prediction or backtest.

## Capture and extraction

- `capture(root, read_payload, *, provider, dataset, request_path, origin, source_timezone=None, requested_offset_minutes=None, content_type="application/json", event_specs=None)` invokes the callback once. It reads the real process UTC wall clock immediately before and after the callback. A backwards clock fails closed. `SCAN_NOW` and caller-specified capture timestamps are not used. The callback must return nonempty `bytes` up to 25 MiB; it is the caller's responsibility not to perform network access in this offline prototype.
- `origin` is `synthetic`, `file_import`, or `provider_response`. Reading a historical file records the **import** time, not original collection time. Context is descriptive: the IANA `source_timezone` and requested offset (minutes east of UTC, independently optional) are declarations, not a proven timezone applied by the provider. Unknown values remain `None`. They need not agree, and neither establishes an event kickoff offset. The source may have cached or old content.
- `request_path` excludes query strings, fragments and URL credentials, but path segments and other supplied metadata can still contain sensitive values. Do not pass tokens, personal information, headers, or sensitive paths as metadata. Response bytes are saved **without redaction**. Ensure collection and retention are lawful and authorized.
- An empty or omitted `event_specs` retains the raw payload but makes **no extracted event or price claims**, including for non-JSON content. Nonempty specs require `application/json`. Each event spec has `event_pointer` from the payload root, `event_id_pointer` relative to that event, and `quotes`. Each quote requires `market_pointer` relative to the event, `market_id_pointer` relative to the market, `outcome_pointer` relative to the market, and `outcome_name_pointer` and `odds_pointer` relative to the outcome. Optional `specifier_pointer` and `market_status_pointer` are relative to the market; `outcome_status_pointer` and `provider_updated_at_pointer` are relative to the outcome. Empty pointer means the current object; RFC 6901 escapes `~0` and `~1` are supported.
- Claimed IDs, names and specifiers must be present string/integer values, and decimal odds must be present, finite and greater than one. Decimal prices are represented as strings without rounding (JSON numeric exponents may be normalized); exact source bytes remain available for inspection. Missing, null, zero or invalid requested prices cause capture to fail rather than become zero. Omit a quote spec to leave a missing price unclaimed. Duplicate JSON keys and duplicate market/outcome/specifier claims within an event are rejected. The extractor verifies pointers and nesting, **not** whether the caller selected the correct provider fields or interpreted a market's meaning correctly.
- Optional status/update values are raw scalar observations, with `None` when not extracted or explicitly null. They are not normalized or evaluated. `provider_updated_at` is not parsed, validated, or used as a freshness timestamp; it is an unverified provider claim. No quote is established to be active, executable, current, settled or in a particular market definition just because it appears here.

## Files, as-of checks and integrity

Each random snapshot-ID directory contains `payload.bin`, `claims.json`, `manifest.json`, and `receipt.json`. Payload and claims have SHA-256 hashes and byte counts in a canonical manifest; the manifest metadata has its own hash. After those three files are materialized, the process records an `available_at_utc` witness and writes a receipt containing the manifest hash and a witness hash. Files are created exclusively and a manifest and receipt are published by hard links; incomplete directories are not readable as committed snapshots. The implementation fsyncs file contents but does not fsync directories, so it does **not** promise crash-durable storage. A filesystem supporting hard links is required.

`load_as_of(path, cutoff, *, allow_non_provider=False, expected_receipt_sha256=None)` requires an aware datetime, verifies the files/hashes, re-extracts claims from the raw payload and their recorded pointers, and requires `available_at_utc <= cutoff`. This is conservative relative to callback return: if processing takes time, the response is not admitted at the earlier response timestamp. The witness is observed *after* the manifest exists and *before* the receipt is published; it is not a certified timestamp or evidence that the receipt had already been published at that instant. Exact equality is allowed. A later capture or incomplete receipt is rejected. To use snapshots for predictions, independently verify that the cutoff is strictly before the correct event kickoff and that all required model inputs and prices meet the same cutoff; this loader does not check kickoff, price staleness, status, market rules or settlement.

The return value contains `metadata`, `availability`, raw `payload`, extracted `claims`, and `receipt_sha256`. To detect later whole-snapshot rewriting, a trusted operator can retain that receipt hash in a **separately controlled, trustworthy external anchor** at capture time and later pass it as `expected_receipt_sha256`. Without such an anchor, anyone who can rewrite the snapshot can also recompute all hashes and timestamps. Even with an anchor, hashes are not signatures, cannot authenticate the provider or clock, and do not prove an independent anchor actually existed at its claimed date. Filesystem path checks are not a security boundary against a hostile local writer or parent-directory replacement. Use access controls and trusted storage.

Directories and files created here request modes `0700` and `0600`, respectively, subject to the platform and umask; pre-existing parents may be more permissive. Store snapshots outside tracked files (the repository's `state/` directory is ignored), restrict and audit access, define retention/deletion, and keep sensitive payloads out of Git and public artifacts. Nothing automatically sanitizes, encrypts, or manages retention.

## Before any future live use

Separately obtain approval for an authorized provider adapter, secure wall-clock monitoring, timezone and identity mapping, provider cache/update semantics, quote/market active and settlement rules, failure handling, private retention and independently anchored digests. Validate a **prospective** chronological holdout against separately captured, genuinely available inputs and quotes. Do not infer historical SportyBet availability, eligibility or ROI from this prototype or from imported archives. Connecting this module to production or collecting live data requires a separate decision.

## Synthetic replay

See [REPLAY.md](REPLAY.md) for the synthetic-only chronological replay, executable demonstration, exact toy assumptions, and prerequisites for a real prospective holdout. It is not a production eligibility or settlement system.

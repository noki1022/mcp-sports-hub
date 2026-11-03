# NBA market capture evidence ledger

This branch stores append-only, compressed, byte-for-byte source JSON files for every available captured NBA board from original GitHub Actions. Files are grouped by Beijing NBA game date and original Actions run ID/attempt. The accompanying `manifest.json` gives each original source's SHA-256, observed capture timestamp, source coverage and exact source filename. Never rewrite entries or force-push this branch.

The main production branch and its PushPlus model pipeline are independent from this archive. Research shadows may only read sanitized pretip copies, not postgame scores.

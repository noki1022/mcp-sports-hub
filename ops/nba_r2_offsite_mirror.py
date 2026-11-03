#!/usr/bin/env python3
"""Optional independent Cloudflare R2 S3 mirror of the immutable Git raw archive.

Never delete, rewrite, or replace objects. Verify bytes downloaded from R2,
not ETag. Manifests upload last; missing credentials cause a hard failure.
This is a secondary copy only: local raw captures remain in Git.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

from nba_raw_vault import (PREFIX, audit, digest, evidence_path, manifest_paths,
                           open_manifest, validate_entry, within)

ROOT_KEY = "nba-market-captures/v1"


def remote_key(relative):
    if not relative.startswith(PREFIX + "/"):
        raise ValueError("REMOTE_BACKUP_PATH_NOT_IN_RAW_ARCHIVE")
    return ROOT_KEY + "/" + relative


def download_hash(client, bucket, key, max_bytes):
    obj = client.get_object(Bucket=bucket, Key=key)
    body = obj["Body"]
    hasher = hashlib.sha256()
    size = 0
    try:
        for chunk in body.iter_chunks(chunk_size=1024 * 1024):
            if not chunk:
                continue
            size += len(chunk)
            if size > max_bytes:
                raise ValueError("REMOTE_OBJECT_EXCEEDS_ORIGINAL_SIZE:" + key)
            hasher.update(chunk)
    finally:
        body.close()
    return hasher.hexdigest(), size


def is_missing(client, bucket, key):
    from botocore.exceptions import ClientError
    try:
        client.head_object(Bucket=bucket, Key=key)
        return False
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in ("404", "NoSuchKey", "NotFound"):
            return True
        raise


def ensure_object(client, bucket, key, raw, kind):
    wanted = digest(raw)
    if is_missing(client, bucket, key):
        # Conditional write prevents racing independent backup workflows from
        # replacing original data. Fail closed if backend rejects this request.
        client.put_object(Bucket=bucket, Key=key, Body=raw,
                          ContentType="application/gzip" if kind == "gzip"
                          else "application/json",
                          Metadata={"sha256": wanted, "vault": "nba-original-capture"},
                          IfNoneMatch="*")
        created = True
    else:
        created = False
    # Check the actual remote bytes: object metadata and ETag alone are insufficient.
    actual, size = download_hash(client, bucket, key, len(raw))
    if actual != wanted or size != len(raw):
        raise ValueError("REMOTE_BACKUP_BYTE_MISMATCH:" + key)
    return created


def mirror(root, client, bucket, day=None):
    manifests = list(manifest_paths(root, day))
    if not manifests:
        raise ValueError("NO_ARCHIVE_TO_REPLICATE")
    outcome = {"manifests_verified": 0, "compressed_files_verified": 0,
               "objects_new": 0, "objects_already_present_verified": 0,
               "bytes_verified_remote": 0, "fully_independent_copy": True,
               "raw_git_archive_preserved": True}
    for rel in manifests:
        doc, manifest_bytes = open_manifest(root, rel)
        # Upload source evidence before the manifest (commit marker).
        for row in doc["files"]:
            validate_entry(root, rel, row)
            source_rel = evidence_path(rel, row)
            archive = within(root, source_rel)
            zipped = archive.read_bytes()
            if digest(zipped) != row["gzip_sha256"]:
                raise ValueError("SOURCE_GZIP_CHANGED_BEFORE_REMOTE_COPY")
            created = ensure_object(client, bucket, remote_key(source_rel), zipped, "gzip")
            outcome["objects_new" if created else "objects_already_present_verified"] += 1
            outcome["compressed_files_verified"] += 1
            outcome["bytes_verified_remote"] += len(zipped)
        created = ensure_object(client, bucket, remote_key(rel), manifest_bytes, "manifest")
        outcome["objects_new" if created else "objects_already_present_verified"] += 1
        outcome["manifests_verified"] += 1
        outcome["bytes_verified_remote"] += len(manifest_bytes)
    return outcome


def restore_from_remote(client, bucket, manifest_key, source_name, output):
    """Restore one exact source, validating both remote gzip and raw SHA256."""
    if not manifest_key.startswith(ROOT_KEY + "/" + PREFIX + "/") or not manifest_key.endswith("/manifest.json"):
        raise ValueError("INVALID_REMOTE_MANIFEST_KEY")
    obj = client.get_object(Bucket=bucket, Key=manifest_key)
    data = obj["Body"].read(12 * 1024 * 1024 + 1)
    obj["Body"].close()
    if len(data) > 12 * 1024 * 1024:
        raise ValueError("REMOTE_MANIFEST_TOO_LARGE")
    doc = json.loads(data)
    from nba_raw_vault import SCHEMA
    if doc.get("schema_version") != SCHEMA:
        raise ValueError("REMOTE_SCHEMA_INVALID")
    match = [row for row in doc.get("files", []) if row.get("relative_original_source") == source_name]
    if len(match) != 1:
        raise ValueError("SOURCE_NOT_PRESENT_IN_REMOTE_MANIFEST")
    row = match[0]
    key = manifest_key.rsplit("/", 1)[0] + "/" + row["compressed_file"]
    if not key.startswith(ROOT_KEY + "/" + PREFIX + "/") or ".." in key.split("/"):
        raise ValueError("REMOTE_PATH_TRAVERSAL")
    item = client.get_object(Bucket=bucket, Key=key)
    zipped = item["Body"].read(row["compressed_bytes"] + 1)
    item["Body"].close()
    if len(zipped) != row["compressed_bytes"] or digest(zipped) != row["gzip_sha256"]:
        raise ValueError("REMOTE_GZIP_CHECKSUM_MISMATCH")
    import gzip
    raw = gzip.decompress(zipped)
    if len(raw) != row["source_bytes"] or digest(raw) != row["source_sha256"]:
        raise ValueError("REMOTE_RAW_CHECKSUM_MISMATCH")
    target = Path(output)
    with target.open("xb") as handle:
        handle.write(raw)
    if digest(target.read_bytes()) != row["source_sha256"]:
        target.unlink()
        raise ValueError("REMOTE_RESTORE_CHECKSUM_MISMATCH")
    return {"status": "RESTORED_AND_INDEPENDENTLY_VERIFIED",
            "sha256": digest(raw), "bytes": len(raw), "path": str(target)}


def s3():
    # Standard botocore S3-compatible client; bucket is private.
    import boto3
    required = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")
    missing = [x for x in required if not os.getenv(x)]
    if missing:
        raise ValueError("OFFSITE_BACKUP_NOT_CONFIGURED_MISSING:" + ",".join(missing))
    account = os.environ["R2_ACCOUNT_ID"]
    if not account or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789" for c in account.lower()):
        raise ValueError("INVALID_R2_ACCOUNT_ID")
    endpoint = "https://" + account + ".r2.cloudflarestorage.com"
    client = boto3.client("s3", endpoint_url=endpoint, region_name="auto",
                          aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                          aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
                          config=__import__("botocore.config", fromlist=["Config"]).Config(
                              retries={"max_attempts": 3, "mode": "standard"},
                              signature_version="s3v4"))
    return client, os.environ["R2_BUCKET"]


def selftest():
    assert remote_key("reports/market-captures/2026-11-03/a/manifest.json") == (
        ROOT_KEY + "/reports/market-captures/2026-11-03/a/manifest.json")
    try:
        remote_key("../escape")
    except ValueError:
        pass
    else:
        raise AssertionError("REMOTE_KEY_ESCAPE_NOT_REJECTED")
    class Fake:
        def __init__(self):
            self.objects = {}
        def head_object(self, Bucket, Key):
            from botocore.exceptions import ClientError
            if Key not in self.objects:
                raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
            return {}
        def put_object(self, Bucket, Key, Body, **kwargs):
            assert kwargs["IfNoneMatch"] == "*"
            if Key in self.objects:
                raise AssertionError("REMOTE_KEY_WOULD_OVERWRITE")
            self.objects[Key] = Body
        def get_object(self, Bucket, Key):
            from io import BytesIO
            class Stream:
                def __init__(self, raw): self.io = BytesIO(raw)
                def iter_chunks(self, chunk_size):
                    while True:
                        x = self.io.read(chunk_size)
                        if not x: break
                        yield x
                def close(self): self.io.close()
            return {"Body": Stream(self.objects[Key])}
    fake = Fake()
    assert ensure_object(fake, "bucket", "key", b"immutable", "gzip")
    assert not ensure_object(fake, "bucket", "key", b"immutable", "gzip")
    try:
        ensure_object(fake, "bucket", "key", b"not-original", "gzip")
    except ValueError:
        pass
    else:
        raise AssertionError("REMOTE_TAMPERING_NOT_REJECTED")
    print("NBA_R2_MIRROR_NO_OVERWRITE_AND_REMOTE_READBACK_SELFTEST_PASSED")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--archive-root", default=".")
    p.add_argument("--day")
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--restore-manifest")
    p.add_argument("--source")
    p.add_argument("--output")
    args = p.parse_args()
    if args.selftest:
        selftest()
        return
    client, bucket = s3()
    if args.restore_manifest:
        if not args.source or not args.output:
            raise ValueError("REMOTE_RESTORE_NEEDS_SOURCE_AND_OUTPUT")
        report = restore_from_remote(client, bucket, args.restore_manifest,
                                     args.source, args.output)
    else:
        report = mirror(Path(args.archive_root), client, bucket, args.day)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError) as exc:
        print("NBA_OFFSITE_BACKUP_FAIL_CLOSED:", repr(exc), file=sys.stderr)
        sys.exit(2)

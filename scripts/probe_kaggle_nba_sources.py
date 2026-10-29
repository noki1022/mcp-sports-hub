#!/usr/bin/env python3
"""Read-only Kaggle metadata/availability probe for two requested NBA sources.

- Anonymous public Kaggle API: no credentials and no user secrets.
- No archives downloaded, no dataset persisted, no training promotion.
- Bounded metadata responses, source/version/license/size/file-list auditing.
- Logs metadata only; no row-level user data or raw odds.
"""
from __future__ import annotations
import json
import re
from urllib.error import HTTPError,URLError
from urllib.request import Request,urlopen

SLUGS=(
  "cviaxmiwnptr/nba-betting-data-october-2007-to-june-2024",
  "chevronronson/nba-stats-dataset",
)
API="https://www.kaggle.com/api/v1/datasets/view/"
MAX_META_BYTES=1500000
MAX_FILE_BYTES=40000000

def get_json(url):
    req=Request(url,headers={
       "User-Agent":"nba-historical-source-auditor/1.0",
       "Accept":"application/json"
    })
    with urlopen(req,timeout=25) as res:
        raw=res.read(MAX_META_BYTES+1)
        if len(raw)>MAX_META_BYTES:
            raise ValueError("OVERSIZED_METADATA_RESPONSE")
        return json.loads(raw),res.status

def metadata(dataset):
    url=API+dataset
    try:
        obj,status=get_json(url)
        if not isinstance(obj,dict):raise ValueError("BAD_METADATA_SHAPE")
        files=[]
        for x in (obj.get("resources") or obj.get("files") or []):
            if isinstance(x,dict):
                size=x.get("totalBytes") or x.get("size") or x.get("sizeBytes")
                files.append({"name":str(x.get("name") or x.get("path") or "")[:160],
                              "size":size,
                              "type":x.get("type"),
                              "schema_columns":len(x.get("columns") or [])})
        result={
          "slug":dataset,"http":status,
          "title":str(obj.get("title",""))[:180],
          "id":obj.get("id"),
          "version":obj.get("currentVersionNumber") or obj.get("versionNumber"),
          "last_updated":obj.get("lastUpdated") or obj.get("lastUpdatedDate"),
          "created":obj.get("creationDate"),
          "license_name":obj.get("licenseName") or ((obj.get("license") or {}).get("name") if isinstance(obj.get("license"),dict) else obj.get("license")),
          "size_bytes":obj.get("totalBytes") or obj.get("sizeBytes"),
          "download_count":obj.get("downloadCount"),
          "resources":files[:35],
          "resources_listed":len(files),
          "metadata_file_list_absent":not bool(files),
          "external_provenance_verified":False,
          "odds_asof_quote_time_verified":False,
          "admit_to_training":False,
          "raw_archive_downloaded":False,
          "source":"KAGGLE_PUBLIC_API_METADATA"
        }
        return result
    except (HTTPError,URLError,ValueError,TimeoutError,OSError,json.JSONDecodeError) as ex:
        return {"slug":dataset,"status":"UNAVAILABLE_METADATA",
                "reason":type(ex).__name__+":"+str(ex)[:150],
                "admit_to_training":False,"raw_archive_downloaded":False}

def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:
        assert all(re.fullmatch(r"[A-Za-z0-9_-]+/[A-Za-z0-9_-]+",s) for s in SLUGS)
        assert MAX_META_BYTES<MAX_FILE_BYTES
        print("KAGGLE_METADATA_PROBE_SELF_TEST_PASS")
        return
    for slug in SLUGS:
        print("KAGGLE_DATASET_METADATA "+json.dumps(metadata(slug),ensure_ascii=False,sort_keys=True),flush=True)
    print("KAGGLE_TRAINING_ADMISSION "+
          json.dumps({"allowed":0,"raw_files_committed":0,
          "next_gate":"zip_entry_schema_and_source_licenses_before_train","timestamped_pre_game_prices_required":True},sort_keys=True),flush=True)

if __name__=="__main__":main()

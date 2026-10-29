#!/usr/bin/env python3
"""Read-only bounded Kaggle NBA betting ZIP inspection. No raw data persisted."""
import io,zipfile,csv,json,hashlib
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
URL="https://www.kaggle.com/api/v1/datasets/download/cviaxmiwnptr/nba-betting-data-october-2007-to-june-2024"
LIMIT=6000000
def main():
    result={"source_url":URL,"training_admitted":0,"archive_saved":False}
    try:
        with urlopen(Request(URL,headers={"User-Agent":"nba-integrity-probe/1.0"}),timeout=35) as r:
            body=r.read(LIMIT+1)
            result["http"]=r.status
            result["content_type"]=r.headers.get("Content-Type")
        if len(body)>LIMIT:raise ValueError("DOWNLOAD_EXCEEDS_6MB")
        result["bytes"]=len(body);result["sha256"]=hashlib.sha256(body).hexdigest()
        if not zipfile.is_zipfile(io.BytesIO(body)):
            raise ValueError("NOT_ZIP_OR_AUTH_CHALLENGE")
        archive=zipfile.ZipFile(io.BytesIO(body))
        files=[]
        for z in archive.infolist():
            x={"name":z.filename[:120],"size":z.file_size,"compressed":z.compress_size}
            if z.is_dir():continue
            if z.file_size>35000000 or z.compress_size>LIMIT: x["status"]="TOO_LARGE_SKIP"
            elif z.filename.lower().endswith(".csv"):
                with archive.open(z) as f:
                    lines=io.TextIOWrapper(f,encoding="utf-8-sig",errors="replace",newline="")
                    rd=csv.reader(lines)
                    x["columns"]=next(rd,[])[:70]
                    x["row_count"]=sum(1 for _ in rd)
                    x["status"]="STRUCTURE_INSPECTED_NOT_TRAINING_APPROVED"
            else:x["status"]="NON_CSV_NOT_INGESTED"
            files.append(x)
        result["entries"]=files
    except (HTTPError,URLError,OSError,ValueError,zipfile.BadZipFile,TimeoutError) as e:
        result["status"]="FETCH_OR_FORMAT_REJECTED";result["reason"]=type(e).__name__+":"+str(e)[:140]
    print("KAGGLE_BETTING_ZIP_PROBE "+json.dumps(result,ensure_ascii=False,sort_keys=True),flush=True)
    print("NO_RAW_DATA_SAVED")
if __name__=="__main__":main()

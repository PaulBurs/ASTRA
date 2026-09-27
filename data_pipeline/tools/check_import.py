"""Smoke test through the running frontend proxy, backend and ML service.

Only a bounded sample is uploaded; the source archive is never modified.
The successful dataset remains available for inspection. No /train call is made.
"""
import argparse
import csv
import io
import json
import time
from itertools import islice
from pathlib import Path
from urllib.request import Request, urlopen


def request(base, path, method="GET", body=None):
    headers = {}
    if isinstance(body, dict):
        body = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    elif body is not None:
        headers["Content-Type"] = "application/octet-stream"
    with urlopen(Request(base + path, data=body, headers=headers, method=method), timeout=60) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="Directory with unpacked CSV tables")
    parser.add_argument("--url", default="http://127.0.0.1:5173")
    parser.add_argument("--rows", type=int, default=1000, help="Rows from each of two event files")
    parser.add_argument("--sample-dir", type=Path, help="Optionally save the small input files for a browser test")
    args = parser.parse_args()
    if not 1 <= args.rows <= 10000:
        parser.error("--rows must be between 1 and 10000")
    journals = sorted(args.archive.glob("ext-journal-*.csv"))[:2]
    if len(journals) != 2:
        parser.error("At least two ext-journal-*.csv files are required")
    files = {}
    for name in ("справочник_каналов_датчиков.csv", "справочник_объектов_диспетчер.csv"):
        files[name] = (args.archive / name).read_bytes()
    source_rows = 0
    for path in journals:
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        with path.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.reader(source)
            writer.writerow(next(reader))
            for row in islice(reader, args.rows):
                writer.writerow(row)
                source_rows += 1
        files["sample-" + path.name] = output.getvalue().encode("utf-8")
    if args.sample_dir:
        args.sample_dir.mkdir(parents=True, exist_ok=True)
        for name, content in files.items():
            (args.sample_dir / name).write_bytes(content)

    job = request(args.url, "/api/datasets", "POST", {"files": [
        {"name": name, "size": len(content)} for name, content in files.items()
    ]})
    path = "/api/datasets/" + job["id"]
    print("dataset_id:", job["id"], flush=True)
    for index, content in enumerate(files.values()):
        request(args.url, f"{path}/files/{index}", "PUT", content)
    request(args.url, path + "/prepare", "POST")
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        job = request(args.url, path)
        if job["status"] in {"ready", "error"} or (job["status"] == "prepared" and job["error"]):
            break
        time.sleep(1)
    assert job["status"] == "ready", job
    counts = job["counts"]
    assert counts["source_rows"] == source_rows, counts
    assert counts["feature_rows"] == counts["event_rows"] > 0, counts
    assert source_rows == sum(counts[k] for k in ("event_rows", "duplicate_rows", "orphan_rows")), counts
    assert len(job["ml_check"]["columns"]) == 28
    assert job["ml_check"]["sample"]
    dashboard = request(args.url, f"/api/dashboard?dataset_id={job['id']}")
    assert len(dashboard["sensors"]) == counts["channels"]
    print(json.dumps({"dataset_id": job["id"], "status": job["status"], "counts": counts,
                      "ml_columns": len(job["ml_check"]["columns"]),
                      "dashboard_sensors": len(dashboard["sensors"])}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Manual probe script for POST/GET/HEAD /api/jobs/{job_id}/files.

Usage (from Galaxy root, with venv active):
    python scripts/probe_job_files_api.py [--galaxy-url http://localhost:8080]

Requires a running Galaxy. Creates a frozen job, fires all request variants,
reports pass/fail per case.
"""
import argparse
import io
import os
import sys
import tempfile

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from galaxy.model import (
    Dataset,
    HistoryDatasetAssociation,
    Job,
)
from galaxy.model.mapping import init
from galaxy.security.idencoding import IdEncodingHelper
from galaxy.util import safe_makedirs

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"


def check(label, condition, detail=""):
    status = PASS if condition else FAIL
    print(f"  [{status}] {label}" + (f" — {detail}" if detail else ""))
    return condition


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--galaxy-url", default="http://localhost:8080")
    parser.add_argument("--id-secret", default="USING THE DEFAULT IS NOT SECURE!")
    parser.add_argument("--db-url", default="sqlite:///database/universe.sqlite")
    args = parser.parse_args()

    BASE = args.galaxy_url.rstrip("/")
    security = IdEncodingHelper(id_secret=args.id_secret)

    print(f"Connecting to DB: {args.db_url}")
    model = init("database/files", args.db_url, create_tables=False)
    sa_session = model.session

    # --- Setup: create frozen job ---
    from sqlalchemy import select

    history = sa_session.scalars(select(model.History)).first()
    user = sa_session.scalars(select(model.User)).first()
    if not history or not user:
        print("No history/user found — creating minimal user+history in DB")
        # Create minimal user
        user = model.User(email="probe_test@example.com", username="probe_test")
        user.set_random_password()
        sa_session.add(user)
        sa_session.commit()
        history = model.History(name="probe_test", user=user)
        sa_session.add(history)
        sa_session.commit()

    # Use temp files directly — no object store needed
    probe_tmpdir = tempfile.mkdtemp(prefix="galaxy_probe_")

    input_path = os.path.join(probe_tmpdir, "input.txt")
    input_content = b"probe test input content\n"
    with open(input_path, "wb") as f:
        f.write(input_content)
    print(f"Using input path: {input_path} ({len(input_content)} bytes)")

    output_dir = os.path.join(probe_tmpdir, "output")
    safe_makedirs(output_dir)
    output_path = os.path.join(output_dir, "output.dat")

    # Create minimal input/output HDAs (needed so job.input_datasets / output_datasets exist)
    input_dataset = Dataset()
    input_dataset.state = Dataset.states.OK
    sa_session.add(input_dataset)
    sa_session.commit()
    input_hda = HistoryDatasetAssociation(history=history, dataset=input_dataset, create_dataset=False, flush=False)
    input_hda.hid = 1
    input_hda.name = "probe_input"
    sa_session.add(input_hda)

    output_dataset = Dataset()
    output_dataset.state = Dataset.states.OK
    sa_session.add(output_dataset)
    sa_session.commit()
    output_hda = HistoryDatasetAssociation(history=history, dataset=output_dataset, create_dataset=False, flush=False)
    output_hda.hid = 9999
    sa_session.add(output_hda)
    sa_session.commit()

    # Create job (frozen — unknown handler prevents state transitions)
    job = Job()
    job.history = history
    job.user = user
    job.handler = "unknown-handler"
    job.state = "running"
    sa_session.add(job)
    job.add_input_dataset("input1", input_hda)
    job.add_output_dataset("output1", output_hda)
    sa_session.commit()

    job_id = security.encode_id(job.id)
    job_key = security.encode_id(job.id, kind="jobs_files")
    api_url = f"{BASE}/api/jobs/{job_id}/files"

    # Create the job working directory so __in_working_directory check passes.
    # DiskObjectStore path: {jobs_directory}/000/{job.id}
    job_work_dir = os.path.abspath(os.path.join("database/jobs_directory", "000", str(job.id)))
    safe_makedirs(job_work_dir)
    output_path = os.path.join(job_work_dir, "output.dat")

    print(f"\nJob DB id: {job.id}  encoded: {job_id}")
    print(f"Job key: {job_key}")
    print(f"Working dir: {job_work_dir}")
    print(f"Output path: {output_path}\n")

    results = []

    # --- Case 1: HEAD ---
    print("1. HEAD (expect 200, body empty, content-length set)")
    r = requests.head(api_url, params={"path": input_path, "job_key": job_key})
    results.append(check("status 200", r.status_code == 200, str(r.status_code)))
    results.append(check("body empty", r.text == "", repr(r.text[:40])))
    results.append(check("content-length set", "content-length" in r.headers, str(r.headers.get("content-length"))))

    # --- Case 2: GET ---
    print("\n2. GET (expect 200, body == file content)")
    r = requests.get(api_url, params={"path": input_path, "job_key": job_key})
    results.append(check("status 200", r.status_code == 200, str(r.status_code)))
    results.append(check("body matches", r.content == input_content, f"{len(r.content)} bytes"))

    # helper: fresh output path for each write test
    def fresh_output():
        p = output_path + f".probe{os.getpid()}"
        if os.path.exists(p):
            os.remove(p)
        return p

    # --- Case 3: POST small multipart — path+job_key as QUERY PARAMS (Pulsar's way) ---
    print("\n3. POST small (<1 MiB) — path+job_key as query params")
    out = fresh_output()
    payload = b"pulsar-output-" * 1000
    r = requests.post(api_url, params={"path": out, "job_key": job_key},
                      files={"file": ("output.dat", io.BytesIO(payload), "application/octet-stream")})
    if r.status_code != 200:
        print(f"  DEBUG body: {r.text[:200]!r}")
    results.append(check("status 200", r.status_code == 200, str(r.status_code)))
    results.append(check("content written", os.path.exists(out) and open(out, "rb").read() == payload,
                         f"{os.path.getsize(out) if os.path.exists(out) else 'missing'} bytes"))

    # --- Case 4: POST large (>2 MiB) — exercises streaming path ---
    print("\n4. POST large (3 MiB) — streaming multipart, query params")
    out = fresh_output()
    large_payload = b"galaxy-job-output-" * (3 * 1024 * 1024 // len("galaxy-job-output-")) + b"tail"
    r = requests.post(api_url, params={"path": out, "job_key": job_key},
                      files={"file": ("large.dat", io.BytesIO(large_payload), "application/octet-stream")})
    results.append(check("status 200", r.status_code == 200, str(r.status_code)))
    results.append(check("content written", os.path.exists(out) and open(out, "rb").read() == large_payload,
                         f"{os.path.getsize(out) if os.path.exists(out) else 'missing'} bytes"))

    # --- Case 5: POST — path+job_key as FORM FIELDS (legacy) ---
    print("\n5. POST — path+job_key as form fields (legacy callers)")
    out = fresh_output()
    r = requests.post(api_url,
                      data={"path": out, "job_key": job_key},
                      files={"file": ("output.dat", io.BytesIO(b"form-field-content"), "application/octet-stream")})
    results.append(check("status 200", r.status_code == 200, str(r.status_code)))
    results.append(check("content written", os.path.exists(out) and open(out, "rb").read() == b"form-field-content"))

    # --- Case 6: POST — __file named param ---
    print("\n6. POST — __file named param")
    out = fresh_output()
    r = requests.post(api_url,
                      data={"path": out, "job_key": job_key},
                      files={"__file": ("output.dat", io.BytesIO(b"underscore-file"), "application/octet-stream")})
    results.append(check("status 200", r.status_code == 200, str(r.status_code)))
    results.append(check("content written", os.path.exists(out) and open(out, "rb").read() == b"underscore-file"))

    # --- Case 7: POST — tool_stdout append mode ---
    print("\n7. POST — tool_stdout append mode (two POSTs, expect concatenated content)")
    stdout_path = output_path + ".tool_stdout"
    if os.path.exists(stdout_path):
        os.remove(stdout_path)
    for chunk in [b"chunk1\n", b"chunk2\n"]:
        requests.post(api_url, params={"path": stdout_path, "job_key": job_key},
                      files={"file": ("stdout", io.BytesIO(chunk), "application/octet-stream")})
    expected = b"chunk1\nchunk2\n"
    got = open(stdout_path, "rb").read() if os.path.exists(stdout_path) else b""
    results.append(check("appended correctly", got == expected, repr(got)))

    # --- Case 8: GET after job state → ok (expect 403) ---
    print("\n8. GET after job transitions to 'ok' (expect 403)")
    job.state = "ok"
    sa_session.add(job)
    sa_session.commit()
    r = requests.get(api_url, params={"path": input_path, "job_key": job_key})
    results.append(check("status 403", r.status_code == 403, str(r.status_code)))

    # --- Teardown ---
    # Use SQL DELETE to skip SQLAlchemy event hooks (avoid __create_version__ compat issues)
    from sqlalchemy import text
    sa_session.execute(text(f"DELETE FROM job WHERE id = {job.id}"))
    sa_session.execute(text(f"DELETE FROM history_dataset_association WHERE id = {input_hda.id}"))
    sa_session.execute(text(f"DELETE FROM history_dataset_association WHERE id = {output_hda.id}"))
    sa_session.execute(text(f"DELETE FROM dataset WHERE id = {input_dataset.id}"))
    sa_session.execute(text(f"DELETE FROM dataset WHERE id = {output_dataset.id}"))
    sa_session.commit()

    # Summary
    passed = sum(results)
    total = len(results)
    print(f"\n{'='*40}")
    print(f"Results: {passed}/{total} checks passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()


import requests
import json
import time
import os
import subprocess
import sys

# Configuration
GALAXY_URL = "http://localhost:8080"  # Adjust if needed
API_KEY = os.environ.get("GALAXY_API_KEY")

if not API_KEY:
    print("Please set GALAXY_API_KEY environment variable.")
    sys.exit(1)

def run_db_shell(command):
    """Run a command in Galaxy's db_shell and return output."""
    process = subprocess.Popen(
        [sys.executable, "scripts/db_shell.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    stdout, stderr = process.communicate(input=command)
    return stdout

def get_job_info(encoded_job_id):
    """Extract job_key and file path for a given job using db_shell."""
    cmd = f"""
from galaxy.model import Job
job_id = app.security.decode_id('{encoded_job_id}')
job = sa_session.get(Job, job_id)
job_key = app.security.encode_id(job.id, kind="jobs_files")
# Get an input dataset path
input_path = job.input_datasets[0].dataset.get_file_name() if job.input_datasets else None
# Get an output dataset path
output_path = job.output_datasets[0].dataset.get_file_name() if job.output_datasets else None
# Get work dir
work_dir = app.object_store.get_filename(job, base_dir="job_work", dir_only=True, extra_dir=str(job.id))

print(json.dumps({{
    "job_key": job_key,
    "input_path": input_path,
    "output_path": output_path,
    "work_dir": work_dir
}}))
"""
    output = run_db_shell(cmd)
    # Find the JSON line in output
    for line in output.splitlines():
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return None

def main():
    # 1. Submit a job that will take some time (e.g. upload or a simple tool)
    # For simplicity, let's just upload a small file, it creates a job.
    print("Submitting a job (via upload)...")
    with open("dummy_input.txt", "w") as f:
        f.write("test content\n")
    
    files = {'files_0|file_data': open('dummy_input.txt', 'rb')}
    data = {
        'tool_id': 'upload1',
        'history_id': None, # Will create new
        'inputs': json.dumps({
            'dbkey': '?',
            'file_type': 'txt',
            'files_0|NAME': 'dummy_input.txt',
        })
    }
    
    # Get histories to find/create one
    histories_resp = requests.get(f"{GALAXY_URL}/api/histories", params={"key": API_KEY})
    if histories_resp.status_code != 200:
        print(f"Failed to get histories: {histories_resp.text}")
        return
    
    history_id = histories_resp.json()[0]['id']
    data['history_id'] = history_id
    
    upload_resp = requests.post(f"{GALAXY_URL}/api/tools", data=data, files=files, params={"key": API_KEY})
    if upload_resp.status_code != 200:
        print(f"Upload failed: {upload_resp.text}")
        return
    
    job_id = upload_resp.json()['jobs'][0]['id']
    print(f"Job submitted! Encoded Job ID: {job_id}")

    # 2. Get the job_key and paths
    print("Extracting job_key and paths via db_shell...")
    job_info = get_job_info(job_id)
    if not job_info:
        print("Failed to get job info from database.")
        return
    
    job_key = job_info['job_key']
    input_path = job_info['input_path']
    output_path = job_info['output_path']
    work_dir = job_info['work_dir']
    
    print(f"Retrieved job_key: {job_key}")
    
    # 3. Test GET /api/jobs/{job_id}/files
    print("\n--- Testing GET endpoint ---")
    if input_path:
        print(f"Testing GET with valid path: {input_path}")
        get_resp = requests.get(
            f"{GALAXY_URL}/api/jobs/{job_id}/files",
            params={"path": input_path, "job_key": job_key}
        )
        print(f"GET Status: {get_resp.status_code}")
        if get_resp.status_code == 200:
            print("GET Success!")
        else:
            print(f"GET Failed: {get_resp.text}")

    print("Testing GET with invalid job_key...")
    get_resp_bad_key = requests.get(
        f"{GALAXY_URL}/api/jobs/{job_id}/files",
        params={"path": input_path, "job_key": "WRONG_KEY"}
    )
    print(f"GET (bad key) Status: {get_resp_bad_key.status_code} (Expect 403)")

    # 4. Test POST /api/jobs/{job_id}/files
    print("\n--- Testing POST endpoint ---")
    test_upload_path = os.path.join(work_dir, "pulsar_test_output.txt")
    print(f"Testing POST to work_dir path: {test_upload_path}")
    
    post_data = {"path": test_upload_path, "job_key": job_key}
    post_files = {"file": ("test.txt", "Pulsar was here!", "text/plain")}
    
    post_resp = requests.post(
        f"{GALAXY_URL}/api/jobs/{job_id}/files",
        data=post_data,
        files=post_files
    )
    print(f"POST Status: {post_resp.status_code}")
    if post_resp.status_code == 200:
        print("POST Success!")
        # Verify file exists on disk
        if os.path.exists(test_upload_path):
            print(f"Verified: File created at {test_upload_path}")
        else:
            print(f"Warning: File NOT found at {test_upload_path} even though API returned 200")
    else:
        print(f"POST Failed: {post_resp.text}")

    print("Testing POST with invalid job_key...")
    post_resp_bad_key = requests.post(
        f"{GALAXY_URL}/api/jobs/{job_id}/files",
        data={"path": test_upload_path, "job_key": "WRONG_KEY"},
        files=post_files
    )
    print(f"POST (bad key) Status: {post_resp_bad_key.status_code} (Expect 403)")

    # 5. Wait for job to finish and test again
    print("\nWaiting for job to finish...")
    while True:
        status_resp = requests.get(f"{GALAXY_URL}/api/jobs/{job_id}", params={"key": API_KEY})
        state = status_resp.json()['state']
        print(f"Job state: {state}")
        if state in ['ok', 'error', 'deleted']:
            break
        time.sleep(2)

    print("\n--- Testing access on finished job ---")
    get_resp_finished = requests.get(
        f"{GALAXY_URL}/api/jobs/{job_id}/files",
        params={"path": input_path, "job_key": job_key}
    )
    print(f"GET (finished job) Status: {get_resp_finished.status_code} (Expect 403)")

if __name__ == "__main__":
    main()

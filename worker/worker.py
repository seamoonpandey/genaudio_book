"""genaudi TTS worker — claims jobs from the API over the private network,
synthesizes, posts the MP3 back. No direct DB or S3 access.
Env: API_URL, WORKER_TOKEN. Run: python worker.py"""
import os
import socket
import time
import traceback

import httpx

import engines

API = os.environ["API_URL"].rstrip("/")
HEADERS = {
    "Authorization": f"Bearer {os.environ['WORKER_TOKEN']}",
    "X-Worker-Id": socket.gethostname(),
}
POLL_SECONDS = 3
PROGRESS_EVERY = 2.0  # seconds between progress posts


def run_once(client: httpx.Client) -> bool:
    """Claim and process one job. Returns False when the queue is empty."""
    r = client.post(f"{API}/internal/jobs/claim", headers=HEADERS, timeout=30)
    if r.status_code == 204:
        return False
    r.raise_for_status()
    job = r.json()
    jid = job["job_id"]
    last_sent = 0.0

    def progress(done, total):
        nonlocal last_sent
        if time.monotonic() - last_sent < PROGRESS_EVERY and done < total:
            return
        last_sent = time.monotonic()
        try:
            client.post(f"{API}/internal/jobs/{jid}/progress",
                        json={"progress": done / total}, headers=HEADERS, timeout=10)
        except httpx.HTTPError:
            pass  # progress is cosmetic; never kill a synth over it

    try:
        engine = engines.get(job["engine"])
        mp3, duration = engine.synthesize(job["text"], job["voice"], progress)
        client.post(
            f"{API}/internal/jobs/{jid}/complete",
            files={"file": ("chapter.mp3", mp3, "audio/mpeg")},
            data={"duration": str(duration)},
            headers=HEADERS, timeout=120,
        ).raise_for_status()
        print(f"job {jid} done ({duration:.0f}s audio)", flush=True)
    except Exception as e:
        traceback.print_exc()
        client.post(f"{API}/internal/jobs/{jid}/fail",
                    json={"error": str(e)}, headers=HEADERS, timeout=30)
    return True


def main():
    print(f"worker up, api={API}", flush=True)
    with httpx.Client() as client:
        while True:
            try:
                if not run_once(client):
                    time.sleep(POLL_SECONDS)
            except httpx.HTTPError as e:
                print(f"api unreachable: {e}", flush=True)
                time.sleep(POLL_SECONDS * 2)


if __name__ == "__main__":
    main()

"""Launch Floci via Docker Compose and ping it until it is up and running."""

import subprocess
import sys
import time

import requests

FLOCI_URL = "http://localhost:4566"


def ping_floci(url: str = FLOCI_URL, timeout: float = 2.0) -> tuple[bool, str]:
    """Ping Floci and return (is_up, status_message)."""
    for path in ("/health", "/_localstack/health", "/"):
        try:
            resp = requests.get(f"{url.rstrip('/')}{path}", timeout=timeout)
            if resp.status_code < 500:
                return True, f"Floci is up at {url} (HTTP {resp.status_code} on {path})"
        except requests.RequestException:
            continue
    return False, f"Floci is not reachable at {url}"


def launch_floci() -> None:
    """Start the Floci container using Docker Compose."""
    print("Starting Floci with `docker compose up -d`...")
    subprocess.run(["docker", "compose", "up", "-d"], check=True)


def wait_for_floci(retries: int = 15, delay: float = 1.0) -> bool:
    """Poll Floci until it responds or retries are exhausted."""
    for attempt in range(1, retries + 1):
        is_up, msg = ping_floci()
        if is_up:
            print(msg)
            return True
        print(f"Waiting for Floci... ({attempt}/{retries})")
        time.sleep(delay)
    print(f"Timed out waiting for Floci at {FLOCI_URL}")
    return False


if __name__ == "__main__":
    launch_floci()
    sys.exit(0 if wait_for_floci() else 1)

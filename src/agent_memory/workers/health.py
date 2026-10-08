"""Atomic heartbeat files for process supervisors; no event/memory content."""

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from uuid import UUID


def heartbeat(tenant: UUID, worker: str, kind: str, reason: str) -> None:
    root = Path(os.environ.get("MEMORY_WORKER_HEALTH_DIR", ".local/worker-health"))
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    identity = hashlib.sha256(f"{tenant}:{worker}:{kind}".encode()).hexdigest()
    path = root / f"{identity}.json"
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    if reason == "NO_JOB_AVAILABLE" and path.exists():
        try:
            previous = json.loads(path.read_text())
            if previous.get("reason_code") == "PROVIDER_CONFIGURATION_ERROR":
                reason = "PROVIDER_CONFIGURATION_ERROR"
        except (OSError, ValueError):
            pass
    temporary.write_text(
        json.dumps({"timestamp": time.time(), "pid": os.getpid(), "reason_code": reason})
    )
    temporary.chmod(0o600)
    temporary.replace(path)


def check(tenant: UUID, worker: str, kind: str, max_age: float) -> bool:
    root = Path(os.environ.get("MEMORY_WORKER_HEALTH_DIR", ".local/worker-health"))
    identity = hashlib.sha256(f"{tenant}:{worker}:{kind}".encode()).hexdigest()
    try:
        data = json.loads((root / f"{identity}.json").read_text())
        os.kill(int(data["pid"]), 0)
        return (
            0 <= time.time() - float(data["timestamp"]) <= max_age
            and data["reason_code"] != "PROVIDER_CONFIGURATION_ERROR"
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--kind", choices=["extraction", "embedding", "dispatch"], required=True)
    parser.add_argument("--max-age", type=float, default=60)
    args = parser.parse_args()
    healthy = check(args.tenant_id, args.worker_id, args.kind, args.max_age)
    print("healthy" if healthy else "unhealthy")
    raise SystemExit(0 if healthy else 1)


if __name__ == "__main__":
    main()

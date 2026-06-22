from __future__ import annotations

import time
from collections import OrderedDict

def should_offload(video_sem_locked: bool, reg: "NodeRegistry") -> bool:
    """Offload a video build only when the master's own video slot is busy AND a
    node is currently alive. Otherwise build locally — exactly today's path."""
    return bool(video_sem_locked and reg.alive())

def resolve_enabled(env: str | None, mode: str, node_count: int) -> bool:
    """Decide whether to run the node API at startup. An explicit env override wins,
    then the `vadana node on/off` mode, else "auto": on iff at least one node is
    registered. So with no nodes added, the API simply never starts."""
    e = (env or "").lower()
    if e in ("1", "on", "true"):
        return True
    if e in ("0", "off", "false"):
        return False
    if mode == "on":
        return True
    if mode == "off":
        return False
    return node_count > 0

class NodeRegistry:
    def __init__(self, heartbeat_ttl: float = 30, claim_ttl: float = 1200):
        self.heartbeat_ttl = heartbeat_ttl
        self.claim_ttl = claim_ttl
        self._seen: dict[str, float] = {}
        self._pending: "OrderedDict[str, dict]" = OrderedDict()
        self._claimed: dict[str, tuple[dict, float]] = {}
        self._progress: dict[str, tuple[str, float]] = {}
        self._results: dict[str, str] = {}
        self._failed: dict[str, str] = {}
        self._allow: dict[str, str] = {}

    def ping(self, name: str) -> None:
        self._seen[name] = time.monotonic()

    def alive(self) -> bool:
        now = time.monotonic()
        return any(now - t < self.heartbeat_ttl for t in self._seen.values())

    def nodes(self) -> list[dict]:
        now = time.monotonic()
        return [{"name": n, "seen_ago": round(now - t, 1),
                 "alive": now - t < self.heartbeat_ttl} for n, t in self._seen.items()]

    def enqueue(self, job_id: str, package_path: str, rec_id: str) -> None:
        self._pending[job_id] = {"job_id": job_id, "package_path": package_path, "rec_id": rec_id}

    def claim(self, name: str) -> dict | None:
        if not self._pending:
            return None
        job_id, job = self._pending.popitem(last=False)
        job["node"] = name
        self._claimed[job_id] = (job, time.monotonic())
        return job

    def package_path(self, job_id: str) -> str | None:
        if job_id in self._claimed:
            return self._claimed[job_id][0]["package_path"]
        j = self._pending.get(job_id)
        return j["package_path"] if j else None

    def set_progress(self, job_id: str, stage: str, pct: float) -> None:
        self._progress[job_id] = (stage, pct)

    def get_progress(self, job_id: str) -> tuple[str, float] | None:
        return self._progress.get(job_id)

    def set_result(self, job_id: str, mp4_path: str) -> None:
        self._results[job_id] = mp4_path
        self._claimed.pop(job_id, None)

    def pop_result(self, job_id: str) -> str | None:
        return self._results.pop(job_id, None)

    def set_failed(self, job_id: str, reason: str) -> None:
        self._failed[job_id] = reason
        self._claimed.pop(job_id, None)

    def pop_failed(self, job_id: str) -> str | None:
        return self._failed.pop(job_id, None)

    def expired(self) -> list[dict]:
        """Claimed jobs past claim_ttl — returned (and dropped) so the caller can
        re-queue them locally. Guards against a node that died mid-render."""
        now = time.monotonic()
        out = []
        for job_id in list(self._claimed):
            job, at = self._claimed[job_id]
            if now - at >= self.claim_ttl:
                out.append(job)
                del self._claimed[job_id]
        return out

    def allow(self, fingerprint: str, name: str) -> None:
        self._allow[fingerprint] = name

    def is_allowed(self, fingerprint: str) -> bool:
        return fingerprint in self._allow

    def name_for(self, fingerprint: str) -> str | None:
        """The node name behind a cert fingerprint, or None if not allow-listed."""
        return self._allow.get(fingerprint)

    def load_allowlist(self, mapping: dict[str, str]) -> None:
        self._allow.update(mapping)

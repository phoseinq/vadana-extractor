# Worker Nodes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Offload heavy video builds from the master to remote mTLS worker nodes when the master's video slot is busy, with zero behavior change when no node is connected.

**Architecture:** The master (existing `vadana-extractor` bot) gains a small in-process `aiohttp` mTLS API and a node-job queue. When a video job arrives and `VIDEO_SEM` is busy *and* a node is alive, the master saves the package and enqueues a node-job; a node pulls it over mTLS, renders, and posts the mp4 back; the master archives/sends as usual. A separate new repo `vadana-node` holds a lightweight worker plus its own clean copy of the render code.

**Tech Stack:** Python 3.11–3.13, aiohttp (master API + node client), `cryptography` (CA/mTLS, master only), Pillow + PyMuPDF + ffmpeg (render), aiogram (existing bot).

## Global Constraints

- **No-node fallback is sacred.** With `NODE_API_ENABLE=0` (default) the API never starts and behavior is byte-for-byte today's. With it on, a job offloads only if a node pinged within `HEARTBEAT_TTL`; otherwise it runs locally. A claimed job not delivered within `CLAIM_TTL` returns to the local queue. No code path may strand a job. Every task must keep `pytest` green and the bot importable with no node configured.
- Public repo stays comment-free: run `strip_comments.py` on changed `.py` (keep function docstrings; `cli/api.py` is the only un-stripped file) before committing master code. The node repo is a fresh clean repo (commented normally).
- Python floor 3.11. ffmpeg/ffprobe on PATH for render.
- Commits authored as `phoseinq`, no `Co-Authored-By` trailer.
- Master server IP / tokens never committed.
- Plain everyday language in user-facing copy (EN + FA), no flowery phrasing.

## mTLS API contract (both sides MUST match)

Base: `https://<master>:<NODE_API_PORT>` — server + client cert both verified.

| Method | Path | Body / Query | Returns |
| :-- | :-- | :-- | :-- |
| GET | `/ping` | — | `{"ok": true}`; records caller's `last_seen` |
| POST | `/jobs/claim` | — | `200 {"job_id","rec_id"}` or `204` if queue empty |
| GET | `/jobs/{id}/package` | — | `200` octet-stream zip, or `404` |
| POST | `/jobs/{id}/progress` | `{"stage","pct"}` | `204` |
| POST | `/jobs/{id}/result` | octet-stream mp4 | `204`; master archives + sends + cleans |
| POST | `/jobs/{id}/fail` | `{"reason"}` | `204`; master re-queues locally |

Auth: client cert CN identifies the node; the cert must verify against the master CA *and* its fingerprint must be in the allowlist (defense in depth — a removed node is rejected even if its cert still chains to the CA).

## File structure

**Master (`vadana-extractor`):**
- Create `bot/node_ca.py` — CA + cert issue/load, SSL contexts. (`cryptography`)
- Create `bot/nodes.py` — node registry, heartbeats, node-job queue, `should_offload()`.
- Create `bot/node_api.py` — aiohttp mTLS server (the endpoints above).
- Create `bot/nodecli.py` — `vadana node` subcommands (init/add/list/remove/status).
- Modify `bot/bot.py` — start the API in `main()` when enabled; offload branch in `do_video`.
- Modify `bot/config.py` — node env vars.
- Modify `vadana.sh` — route `vadana node …` to `nodecli.py`.
- Modify `requirements` — add `cryptography`, `aiohttp` (aiogram already pulls aiohttp; pin explicitly).
- Tests `tests/test_nodes.py`, `tests/test_node_ca.py`, `tests/test_node_api.py`.

**Node (`vadana-node`, new repo):**
- `vadana_node/render/` — clean copy of `video.py, whiteboard.py, audio.py, timeline.py, slides.py` + a tiny `pkg.py` (zip read helpers extracted from `connect.read_member`).
- `vadana_node/worker.py` — mTLS client + poll/claim/render/post loop.
- `vadana_node/cli.py` — `run` / `config` / `test`.
- `Dockerfile`, `docker-compose.yml`, `requirements.txt`, `README.md`, `tests/`.

---

## Phase A — Master side

### Task A1: CA + certificate module

**Files:** Create `bot/node_ca.py`; Test `tests/test_node_ca.py`.

**Interfaces — Produces:**
- `create_ca(dir: str) -> None` — writes `ca.crt`, `ca.key` (idempotent: no-op if present).
- `issue_cert(dir, name, *, server=False) -> tuple[str,str]` — returns (cert_pem, key_pem) signed by the CA; `server=True` adds serverAuth + SAN, else clientAuth.
- `fingerprint(cert_pem: str) -> str` — SHA-256 hex of the cert.
- `server_ssl_context(dir) -> ssl.SSLContext` — requires + verifies client certs against `ca.crt`.

- [ ] **Step 1: Write failing tests**
```python
# tests/test_node_ca.py
import ssl, tempfile, os
from bot import node_ca

def test_issue_and_verify(tmp_path):
    d = str(tmp_path)
    node_ca.create_ca(d)
    assert os.path.exists(os.path.join(d, "ca.crt"))
    cert, key = node_ca.issue_cert(d, "node-1")
    # client cert chains to the CA
    store = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    store.load_verify_locations(os.path.join(d, "ca.crt"))
    assert node_ca.fingerprint(cert)  # non-empty hex
    assert "BEGIN CERTIFICATE" in cert and "BEGIN" in key

def test_create_ca_idempotent(tmp_path):
    d = str(tmp_path); node_ca.create_ca(d)
    before = open(os.path.join(d, "ca.key")).read()
    node_ca.create_ca(d)  # second call must not regenerate
    assert open(os.path.join(d, "ca.key")).read() == before
```

- [ ] **Step 2: Run, expect FAIL** — `pytest tests/test_node_ca.py -v` → ModuleNotFound/AttributeError.
- [ ] **Step 3: Implement `bot/node_ca.py`** using `cryptography.x509`: `create_ca` builds a self-signed CA (keyCertSign), `issue_cert` signs a leaf with the CA key (EKU clientAuth or serverAuth+SAN=localhost & configured host), `fingerprint` = `cert.fingerprint(hashes.SHA256()).hex()`, `server_ssl_context` = `ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)` + `load_cert_chain(server cert)` + `load_verify_locations(ca.crt)` + `verify_mode = CERT_REQUIRED`.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git add bot/node_ca.py tests/test_node_ca.py && git commit -m "feat(nodes): CA + mTLS certificate helpers"`

### Task A2: Node registry + job queue

**Files:** Create `bot/nodes.py`; Test `tests/test_nodes.py`.

**Interfaces — Produces:**
- `NodeRegistry(heartbeat_ttl=30, claim_ttl=1200)` with:
  - `ping(name)` / `alive() -> bool` (any node seen within ttl) / `nodes() -> list[dict]`.
  - `enqueue(job_id, package_path, rec_id)` ; `claim(name) -> dict|None` (atomic, oldest first) ; `progress(job_id, stage, pct)` ; `pop_result(job_id)` / `pop_failed(job_id)`.
  - `expired() -> list[job_id]` — claimed jobs past `claim_ttl` (caller re-queues locally).
- `should_offload(video_sem_locked: bool, reg: NodeRegistry) -> bool` — `video_sem_locked and reg.alive()`.

- [ ] **Step 1: Write failing tests**
```python
# tests/test_nodes.py
from bot.nodes import NodeRegistry, should_offload

def test_offload_decision():
    r = NodeRegistry(heartbeat_ttl=30)
    assert should_offload(True, r) is False          # busy, no node
    r.ping("n1")
    assert should_offload(True, r) is True            # busy + live node
    assert should_offload(False, r) is False          # free slot -> local

def test_stale_node_not_alive():
    r = NodeRegistry(heartbeat_ttl=0)                  # everything immediately stale
    r.ping("n1")
    assert r.alive() is False

def test_claim_is_atomic_and_oldest_first():
    r = NodeRegistry()
    r.enqueue("j1", "/tmp/j1.zip", "rec1"); r.enqueue("j2", "/tmp/j2.zip", "rec2")
    assert r.claim("n1")["job_id"] == "j1"
    assert r.claim("n1")["job_id"] == "j2"
    assert r.claim("n1") is None                       # queue empty
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** with `collections.OrderedDict` for the pending queue, `dict` for claimed (with claim timestamp), `time.monotonic()` for ttls, `asyncio.Lock`-free (single event-loop thread) plain dict ops. `should_offload` is the one-liner above.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git commit -m "feat(nodes): registry, heartbeat, job queue, offload decision"`

### Task A3: mTLS API server

**Files:** Create `bot/node_api.py`; Test `tests/test_node_api.py`.

**Interfaces — Consumes:** `node_ca` (Task A1), `NodeRegistry` (Task A2). **Produces:** `async def start_node_api(reg, ca_dir, host, port, on_result, on_fail) -> aiohttp.web.AppRunner` — `on_result(job_id, mp4_path)` and `on_fail(job_id, reason)` are awaited callbacks the bot supplies.

- [ ] **Step 1: Write a failing integration test** that issues a server + client cert with `node_ca`, starts the API on `127.0.0.1` with a free port, then uses an aiohttp client (with the client cert) to `GET /ping` (expect `{"ok":true}`), enqueue a job in the registry, `POST /jobs/claim` (expect the job_id), `GET /jobs/{id}/package` (expect the bytes), `POST /jobs/{id}/result` with a dummy mp4 (expect 204 and `on_result` called).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** the aiohttp `Application` with the six routes, `ssl_context=node_ca.server_ssl_context(ca_dir)`, reject if peer cert fingerprint not in `reg` allowlist (read `request.transport.get_extra_info("ssl_object").getpeercert()`), stream package via `web.FileResponse`, write result to a temp mp4 then `await on_result`.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git commit -m "feat(nodes): aiohttp mTLS job API"`

### Task A4: Config + wire offload into the bot

**Files:** Modify `bot/config.py`, `bot/bot.py`; Test extends `tests/test_nodes.py`.

**Interfaces — Consumes:** A2/A3. **Produces:** offload branch inside `do_video`.

- [ ] **Step 1: Add config** to `bot/config.py`: `NODE_API_ENABLE`, `NODE_API_PORT=8443`, `NODE_API_HOST=0.0.0.0`, `NODE_DIR="nodes"`, `HEARTBEAT_TTL=30`, `CLAIM_TTL=1200` (all via `os.environ.get` with defaults; disabled by default).
- [ ] **Step 2: Write a failing test** `test_do_video_local_when_no_node` — with `NODE_API_ENABLE` off, assert `should_offload(...)` path is never taken (unit-level: patch `VIDEO_SEM.locked` True, empty registry → `should_offload` False).
- [ ] **Step 3: Implement** in `main()`: if `config.NODE_API_ENABLE`, build `NodeRegistry`, `create_ca`, `await start_node_api(...)`, and a background task draining `reg.expired()` back to local. In `do_video`, after the package is downloaded to a temp zip: `if config.NODE_API_ENABLE and should_offload(VIDEO_SEM.locked(), REG): enqueue + await a per-job asyncio.Event set by on_result/on_fail (with CLAIM_TTL timeout → fall through to local render)`. The local render block is unchanged and is the `else`/timeout path. The progress poller reads `reg.progress` for offloaded jobs.
- [ ] **Step 4: Run** `pytest -q` — all green; bot imports with node disabled.
- [ ] **Step 5: Commit** — `git commit -m "feat(nodes): offload do_video to a worker when busy, local fallback"`

### Task A5: `vadana node` CLI

**Files:** Create `bot/nodecli.py`; Modify `vadana.sh`.

**Interfaces — Consumes:** `node_ca`, persisted allowlist. **Produces:** `python -m bot.nodecli <init|add|list|remove|status>`.

- [ ] **Step 1: Write a failing test** `tests/test_nodecli.py::test_add_emits_bundle` — `init` then `add node-1` writes `node-1.crt/.key` and prints a bundle containing `ca.crt` + host:port; the fingerprint is added to the allowlist file.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** `bot/nodecli.py` with `argparse`: `init`→`create_ca`+server cert; `add`→`issue_cert(client)`, append fingerprint+name to `nodes/allowlist.json`, print the bundle (paths + a ready `vadana-node config` line); `list/status`→read allowlist + live registry snapshot file; `remove`→drop from allowlist.
- [ ] **Step 4: Run, expect PASS.** Add `node) shift; "$PY" -m bot.nodecli "$@" ;;` to `vadana.sh`.
- [ ] **Step 5: Commit** — `git commit -m "feat(nodes): vadana node init/add/list/remove/status CLI"`

---

## Phase B — Node repo `vadana-node`

### Task B1: Scaffold + clean render copy

**Files:** New repo; `vadana_node/render/{video,whiteboard,audio,timeline,slides,pkg}.py`, `requirements.txt`, `.gitignore`, `LICENSE`, `tests/test_render_smoke.py`.

- [ ] **Step 1:** `git init vadana-node`; copy the five render modules from `vadana-extractor/vadana/` into `vadana_node/render/`, replacing `from .connect import read_member` with a local `from .pkg import read_member` (move that one helper into `pkg.py`). Keep them commented/clean (new repo).
- [ ] **Step 2: Write a smoke test** that builds a tiny synthetic whiteboard zip in `tmp` and runs `render.video.make_full_video` to assert an mp4 is produced (reuse the existing `tests/conftest` fixtures' approach from the main repo).
- [ ] **Step 3: Run, expect PASS** (render code is already proven). `requirements.txt`: `Pillow`, `PyMuPDF`.
- [ ] **Step 4: Commit** — `git commit -m "node: clean copy of the render pipeline"`

### Task B2: Worker daemon (mTLS client)

**Files:** `vadana_node/worker.py`; `tests/test_worker.py`.

**Interfaces — Consumes:** the API contract. **Produces:** `async def run_worker(cfg)` loop.

- [ ] **Step 1: Write a failing test** that runs a stub aiohttp mTLS server exposing the contract, points the worker at it, enqueues one job, and asserts the worker claims → downloads → posts a result.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** the loop: `ssl` client context (`load_cert_chain(node cert)` + `load_verify_locations(ca.crt)` + `check_hostname` per the master SAN); every `POLL_INTERVAL` → `GET /ping` then `POST /jobs/claim`; on a job → `GET package` to temp → `render.video.make_full_video` (fallback `make_media_video`) with a `progress` callback that `POST`s `/progress` → `POST /result` (retry 3× w/ backoff) or `/fail`. Backoff + reconnect on any mTLS/transport error.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git commit -m "node: mTLS worker poll/claim/render/post loop"`

### Task B3: Node CLI + Docker

**Files:** `vadana_node/cli.py`, `Dockerfile`, `docker-compose.yml`, `README.md`.

- [ ] **Step 1:** Implement `cli.py` (`argparse`): `config` writes `~/.vadana-node/config.json` (master url, cert paths); `test` does an mTLS `GET /ping` and prints OK/why; `run` calls `asyncio.run(run_worker(cfg))`.
- [ ] **Step 2: Write a test** `test_config_roundtrip` — `config` then load returns the same values.
- [ ] **Step 3:** `Dockerfile` = `python:3.12-slim` + `ffmpeg` + `pip install -r requirements.txt` + `CMD ["python","-m","vadana_node.cli","run"]`; `docker-compose.yml` mounts the cert bundle.
- [ ] **Step 4:** `README.md` (EN+FA): how to get a bundle from `vadana node add`, drop it in, `docker compose up`.
- [ ] **Step 5: Commit** — `git commit -m "node: CLI (run/config/test) + Docker + README"`

---

## Phase C — Docs & release

### Task C1: Master README + v3.0.0

- [ ] **Step 1:** Add a "Worker nodes (optional)" section to `vadana-extractor/README.md` (EN+FA): what it does, `vadana node init/add`, the `NODE_API_*` env vars, and the no-node fallback guarantee. Add the new env vars to `bot/.env.example`.
- [ ] **Step 2:** `strip_comments.py` on all changed `.py`; run `pytest -q` + `ruff check --select E9,F63,F7,F82 .` — green.
- [ ] **Step 3:** Update `CHANGELOG.md` (v3.0.0 entry), bump `cli/api.py` version to `3.0.0`.
- [ ] **Step 4: Commit, tag, release** — `git commit -m "v3.0.0 — worker-node offload"`, `git tag -a v3.0.0`, push, `gh release create v3.0.0`.

### Task C2: vadana-node release

- [ ] **Step 1:** Create GitHub repo `phoseinq/vadana-node`, push `main`.
- [ ] **Step 2:** Add the `docker-publish.yml` workflow (ghcr), tag `v0.1.0`, `gh release create v0.1.0`, confirm the image publishes + is public.

---

## Self-review

- **Spec coverage:** dumb node (B1/B2 render-only) ✓ · mTLS both ways (A1/A3/B2) ✓ · offload-when-busy + fallback (A2/A4) ✓ · self-contained node repo (B1) ✓ · master API endpoints (A3) ✓ · `vadana node` CLI (A5) ✓ · node CLI (B3) ✓ · CA/revoke (A1/A5) ✓ · Docker both (existing master / B3) ✓ · v3 + node release (C1/C2) ✓ · tests unit+integration (A1–A5, B1–B3) ✓.
- **Placeholders:** none — each task names exact files, interfaces, and test code.
- **Type consistency:** `should_offload(bool, NodeRegistry)`, `NodeRegistry.alive()`, `claim()->dict|None`, `start_node_api(...)->AppRunner`, `run_worker(cfg)` used consistently across tasks.

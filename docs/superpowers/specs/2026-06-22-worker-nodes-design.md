# Worker Nodes — offloading heavy video builds

## Goal

Offload heavy video rendering from the master server to one or more remote worker
nodes **when the master's video slot is busy**, so fewer
jobs wait in the queue. Nodes are lightweight, pure-compute, and connect to the
master over mutually-authenticated TLS (mTLS).

## Agreed decisions

- **Dumb compute node.** The master downloads the package from the Iran source and
  uploads the finished video to Telegram. The node only renders. The node never
  touches the Iran proxy or Telegram, and holds no secrets.
- **mTLS, node-initiated (pull).** The node opens the connection to the master, so
  it works behind NAT. Both sides verify each other's certificate.
- **Offload when busy.** A video job is offloaded only if the master's `VIDEO_SEM`
  is busy *and* a live node exists. Otherwise it stays in the master's local queue
  exactly as today — no job is ever stranded.
- **Self-contained node repo.** The node lives in a new repo `vadana-node` with its
  own clean copy of the render modules; the node installs from its own repo (no
  submodule, no pip-from-main).
- **Video only.** Files and whiteboard PDFs are cheap; only the heavy video path is
  offloaded.

## Architecture / data flow

```
user → bot on master → downloads package from Iran (unchanged)
        ├─ VIDEO_SEM free?          → render locally (unchanged)
        ├─ busy + a live node?      → enqueue as a node-job (package saved to temp)
        └─ busy + no live node?     → local queue (unchanged)

node (mTLS → master API):  ping → claim → GET package → render(+denoise)
                           → POST progress … → POST result (mp4)
master: archive to channel + send to user + delete temp
   (node failure / timeout → job returns to the local queue)
```

## Components

### A. Master — changes in `vadana-extractor`

1. **mTLS job API** — an `aiohttp` server in the bot's event loop, on a configurable
   port (default `8443`), with an SSL context that *requires and verifies* a client
   cert against the local CA.
   - `GET  /ping` — heartbeat; records the node's `last_seen`.
   - `POST /jobs/claim` — atomically hand the oldest queued node-job to the caller;
     returns `{job_id, rec_id}` or `204` when the queue is empty.
   - `GET  /jobs/{id}/package` — stream the recording package zip for a claimed job.
   - `POST /jobs/{id}/progress` — `{stage, pct}`; updates the user's live status msg.
   - `POST /jobs/{id}/result` — upload of the finished mp4; master takes over
     (archive + send + cleanup).
   - `POST /jobs/{id}/fail` — node reports failure; master re-queues the job locally.
2. **Offload logic** in `bot.py`: in `do_video`, after the package is in hand, if
   `VIDEO_SEM.locked()` and a node pinged within `HEARTBEAT_TTL` (default 30 s),
   persist the package to `node_jobs/<job_id>.zip`, enqueue the job, and set the
   user's status to "processing on a worker node". A claimed job has a `CLAIM_TTL`
   deadline; if the node neither delivers nor pings before it expires, the job goes
   back to the local queue.
3. **Node registry + CA** under `nodes/`: the CA (`ca.crt`/`ca.key`, created once),
   the master server cert, and an allowlist of node certs (by CN + fingerprint).
4. **Config (env):** `NODE_API_ENABLE` (default 0), `NODE_API_PORT` (8443),
   `NODE_API_HOST` (0.0.0.0), cert paths, `HEARTBEAT_TTL`, `CLAIM_TTL`.

### B. Master CLI — `vadana node …`

- `vadana node init` — create the CA + master server cert (once).
- `vadana node add <name>` — issue a client cert/key signed by the CA and print a
  ready bundle (`master host:port` + `ca.crt` + `node.crt` + `node.key`) to drop on
  the node; adds the cert to the allowlist.
- `vadana node list` / `status` — nodes, `last_seen`, current job.
- `vadana node remove <name>` — drop from the allowlist (revoke).

### C. Node — new repo `vadana-node`

- **Worker daemon:** loop → `ping` + `claim`; on a job: `GET package` → render with
  the bundled render code (`make_full_video` / `make_media_video`, denoise on) →
  `POST progress` while rendering → `POST result` (or `POST fail`). All over mTLS
  with the node's client cert.
- **Own clean copy** of the render modules (`video`, `whiteboard`, `audio`,
  `timeline`, `slides`, plus the minimal zip-read helper), depending only on
  `Pillow + PyMuPDF + ffmpeg`. No aiogram, no Iran download, no Telegram.
- **Node CLI** (`vadana-node`): `run` (start worker), `config` (set master url +
  cert paths → config file), `test` (verify the mTLS handshake + a tiny round-trip).
- **Dockerfile:** `python:3.12-slim` + ffmpeg + Pillow + PyMuPDF.

## Failure handling

- Node dies mid-render / stops pinging → `CLAIM_TTL` expires → master re-queues
  locally.
- Result upload fails → node retries a few times, then `POST /fail`.
- mTLS handshake fails → master refuses; node logs and retries with backoff.
- **No node ever connects → behaviour is identical to today** (local queue only).

## Security

mTLS both directions. The node pins the master's CA; the master verifies the node
cert against the allowlist. The CA key never leaves the master. Revoke = remove from
the allowlist + `node remove`. The package and result travel only over the mTLS
channel; the node stores no Telegram token and no Iran proxy.

## Repos & release

- `vadana-extractor` → **v3.0.0**: master API + offload + `vadana node` CLI + README
  section. No behaviour change when no nodes are configured (`NODE_API_ENABLE=0`).
- `vadana-node` (new): worker + render copy + node CLI + Docker + README + tag
  `v0.1.0`.

## Testing

- **Unit:** offload decision (busy+node → offload, busy+no-node → local, free →
  local); CA issue/verify; claim-queue atomicity.
- **Integration:** a full fake job round-trip over mTLS on localhost — a test node
  claims, fetches a tiny package, returns a result; assert the master archives + sends.

## Out of scope (YAGNI)

- More than one job per node at a time.
- Auto-scaling / node auto-discovery (nodes are added by hand via the CLI).
- Offloading the files / whiteboard paths.
- A web dashboard (CLI `status` is enough).

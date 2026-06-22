import asyncio
import os
import socket

import aiohttp

from bot import node_ca
from bot.nodes import NodeRegistry
from bot.node_api import start_node_api


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _setup_certs(d):
    node_ca.create_ca(d)
    node_ca.issue_cert(d, "_server", server=True, out_prefix="server")


def _client_ctx(d, prefix):
    return node_ca.client_ssl_context(os.path.join(d, "ca.crt"),
                                      os.path.join(d, f"{prefix}.crt"),
                                      os.path.join(d, f"{prefix}.key"))


def test_full_job_roundtrip_over_mtls(tmp_path):
    asyncio.run(_roundtrip(str(tmp_path)))


async def _roundtrip(d):
    _setup_certs(d)
    cert, _ = node_ca.issue_cert(d, "node-1", out_prefix="node-1")
    reg = NodeRegistry()
    reg.allow(node_ca.fingerprint(cert), "node-1")

    pkg = os.path.join(d, "pkg.zip")
    open(pkg, "wb").write(b"PK\x03\x04hello")
    reg.enqueue("job1", pkg, "rec1")

    results = {}

    async def on_result(jid, path):
        results[jid] = path

    async def on_fail(jid, reason):
        results[jid] = ("fail", reason)

    port = _free_port()
    runner = await start_node_api(reg, d, "127.0.0.1", port, on_result, on_fail)
    try:
        conn = aiohttp.TCPConnector(ssl=_client_ctx(d, "node-1"))
        async with aiohttp.ClientSession(connector=conn, base_url=f"https://127.0.0.1:{port}") as s:
            assert await (await s.get("/ping")).json() == {"ok": True}
            assert reg.alive() is True                       # the ping registered a heartbeat
            j = await (await s.post("/jobs/claim")).json()
            assert j["job_id"] == "job1" and j["rec_id"] == "rec1"
            assert await (await s.get("/jobs/job1/package")).read() == b"PK\x03\x04hello"
            r = await s.post("/jobs/job1/progress", json={"stage": "encode", "pct": 40})
            assert r.status == 204
            assert reg.get_progress("job1") == ("encode", 40.0)
            r = await s.post("/jobs/job1/result", data=b"MP4DATA")
            assert r.status == 204
        assert open(results["job1"], "rb").read() == b"MP4DATA"
    finally:
        await runner.cleanup()


def test_ca_valid_but_unallowed_cert_is_rejected(tmp_path):
    asyncio.run(_reject(str(tmp_path)))


async def _reject(d):
    _setup_certs(d)
    node_ca.issue_cert(d, "rogue", out_prefix="rogue")       # chains to the CA, but not allow-listed
    reg = NodeRegistry()                                     # empty allowlist

    async def cb(*a):
        pass

    port = _free_port()
    runner = await start_node_api(reg, d, "127.0.0.1", port, cb, cb)
    try:
        conn = aiohttp.TCPConnector(ssl=_client_ctx(d, "rogue"))
        async with aiohttp.ClientSession(connector=conn, base_url=f"https://127.0.0.1:{port}") as s:
            assert (await s.get("/ping")).status == 403
    finally:
        await runner.cleanup()

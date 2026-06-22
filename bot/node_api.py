"""
The master's mTLS job API that worker nodes pull from. Runs as an aiohttp server
inside the bot's event loop. Every request is over TLS with a client certificate;
on top of CA verification we also require the cert's fingerprint to be in the
registry allowlist, so a removed node is rejected even if its cert still chains.
"""
from __future__ import annotations

import hashlib
import os
import tempfile

from aiohttp import web

from . import node_ca

_MAX_RESULT = 3 * 1024 ** 3  # a finished mp4 can be large; cap generously


def _peer_fingerprint(request) -> str | None:
    ssl_obj = request.transport.get_extra_info("ssl_object")
    der = ssl_obj.getpeercert(binary_form=True) if ssl_obj else None
    return hashlib.sha256(der).hexdigest() if der else None


def _node_name(request, reg):
    """The allow-listed node behind this connection's client cert, or None."""
    fp = _peer_fingerprint(request)
    return reg.name_for(fp) if fp else None


def _make_app(reg, on_result, on_fail) -> web.Application:
    routes = web.RouteTableDef()

    @routes.get("/ping")
    async def ping(request):
        name = _node_name(request, reg)
        if not name:
            return web.Response(status=403)
        reg.ping(name)
        return web.json_response({"ok": True})

    @routes.post("/jobs/claim")
    async def claim(request):
        name = _node_name(request, reg)
        if not name:
            return web.Response(status=403)
        job = reg.claim(name)
        if job is None:
            return web.Response(status=204)
        return web.json_response({"job_id": job["job_id"], "rec_id": job["rec_id"]})

    @routes.get("/jobs/{id}/package")
    async def package(request):
        if not _node_name(request, reg):
            return web.Response(status=403)
        path = reg.package_path(request.match_info["id"])
        if not path or not os.path.exists(path):
            return web.Response(status=404)
        return web.FileResponse(path)

    @routes.post("/jobs/{id}/progress")
    async def progress(request):
        if not _node_name(request, reg):
            return web.Response(status=403)
        data = await request.json()
        reg.set_progress(request.match_info["id"], str(data.get("stage", "")), float(data.get("pct", 0)))
        return web.Response(status=204)

    @routes.post("/jobs/{id}/result")
    async def result(request):
        if not _node_name(request, reg):
            return web.Response(status=403)
        jid = request.match_info["id"]
        fd, path = tempfile.mkstemp(suffix=".mp4", prefix=f"node_{jid}_")
        os.close(fd)
        with open(path, "wb") as f:
            async for chunk in request.content.iter_chunked(65536):
                f.write(chunk)
        reg.set_result(jid, path)
        await on_result(jid, path)
        return web.Response(status=204)

    @routes.post("/jobs/{id}/fail")
    async def fail(request):
        if not _node_name(request, reg):
            return web.Response(status=403)
        jid = request.match_info["id"]
        data = await request.json()
        reg.set_failed(jid, str(data.get("reason", "")))
        await on_fail(jid, str(data.get("reason", "")))
        return web.Response(status=204)

    app = web.Application(client_max_size=_MAX_RESULT)
    app.add_routes(routes)
    return app


async def start_node_api(reg, ca_dir, host, port, on_result, on_fail) -> web.AppRunner:
    """Start the mTLS API; returns the AppRunner (call .cleanup() to stop).
    on_result(job_id, mp4_path) / on_fail(job_id, reason) are awaited callbacks."""
    app = _make_app(reg, on_result, on_fail)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port, ssl_context=node_ca.server_ssl_context(ca_dir))
    await site.start()
    return runner

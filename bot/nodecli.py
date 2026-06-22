from __future__ import annotations

import argparse
import json
import os
import sys

from bot import node_ca

def _dir(args) -> str:
    return args.dir or os.environ.get("NODE_DIR", "nodes")

def _allow_path(d: str) -> str:
    return os.path.join(d, "allowlist.json")

def _load_allow(d: str) -> dict:
    try:
        with open(_allow_path(d), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def _save_allow(d: str, mapping: dict) -> None:
    with open(_allow_path(d), "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2)

def _sans(args) -> list[str]:
    sans = ["localhost", "127.0.0.1"]
    if getattr(args, "host", None):
        sans.append(args.host)
    return sans

def _ensure_ca(d: str, args) -> None:
    node_ca.create_ca(d)
    if not os.path.exists(os.path.join(d, "server.crt")):
        node_ca.issue_cert(d, "master", server=True, out_prefix="server", sans=_sans(args))

def cmd_init(args) -> None:
    d = _dir(args)
    _ensure_ca(d, args)
    print(f"✓ CA ready in {d}/  (ca.crt, server.crt). Now: vadana node add <name> --host <MASTER_IP>")

def cmd_add(args) -> None:
    d = _dir(args)
    _ensure_ca(d, args)
    prefix = f"node-{args.name}"
    cert, _ = node_ca.issue_cert(d, args.name, out_prefix=prefix)
    allow = {fp: n for fp, n in _load_allow(d).items() if n != args.name}
    allow[node_ca.fingerprint(cert)] = args.name
    _save_allow(d, allow)

    host = args.host or "<MASTER_HOST>"
    port = args.port or os.environ.get("NODE_API_PORT", "8443")
    print(f"""✓ node "{args.name}" registered.

Copy these 3 files to the node:
    {os.path.join(d, 'ca.crt')}
    {os.path.join(d, prefix + '.crt')}
    {os.path.join(d, prefix + '.key')}

Then on the node:
    vadana-node config --master https://{host}:{port} \\
        --ca ca.crt --cert {prefix}.crt --key {prefix}.key
    vadana-node test          # verify the mTLS connection
    vadana-node run           # or: docker compose up -d""")

def cmd_list(args) -> None:
    allow = _load_allow(_dir(args))
    if not allow:
        print("no nodes registered.")
        return
    for fp, name in allow.items():
        print(f"  {name:20} {fp[:16]}…")

def cmd_remove(args) -> None:
    d = _dir(args)
    allow = _load_allow(d)
    gone = [fp for fp, n in allow.items() if n == args.name]
    for fp in gone:
        del allow[fp]
    _save_allow(d, allow)
    print(f"✓ removed {args.name}" if gone else f"no node named {args.name}")

def _common(sp):
    sp.add_argument("--dir", help="node directory (default ./nodes or $NODE_DIR)")
    sp.add_argument("--host", help="master host/IP the node will connect to")
    sp.add_argument("--port", help="master node-API port (default 8443)")

def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser(prog="vadana node")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("init", "list", "status"):
        _common(sub.add_parser(name))
    for name in ("add", "remove"):
        sp = sub.add_parser(name)
        sp.add_argument("name")
        _common(sp)
    args = p.parse_args(argv)
    {"init": cmd_init, "add": cmd_add, "list": cmd_list,
     "status": cmd_list, "remove": cmd_remove}[args.cmd](args)
    return 0

if __name__ == "__main__":
    sys.exit(main())

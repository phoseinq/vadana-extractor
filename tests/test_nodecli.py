import json
import os

from bot import nodecli


def test_add_registers_and_emits_bundle(tmp_path, capsys):
    d = str(tmp_path)
    nodecli.main(["init", "--dir", d])
    nodecli.main(["add", "node-1", "--dir", d, "--host", "1.2.3.4", "--port", "8443"])
    out = capsys.readouterr().out
    assert os.path.exists(os.path.join(d, "node-node-1.crt"))
    assert os.path.exists(os.path.join(d, "node-node-1.key"))
    allow = json.load(open(os.path.join(d, "allowlist.json")))
    assert "node-1" in allow.values()
    assert "1.2.3.4" in out and "ca.crt" in out          # the bundle tells the user what to copy


def test_remove_drops_from_allowlist(tmp_path):
    d = str(tmp_path)
    nodecli.main(["init", "--dir", d])
    nodecli.main(["add", "node-1", "--dir", d])
    nodecli.main(["remove", "node-1", "--dir", d])
    allow = json.load(open(os.path.join(d, "allowlist.json")))
    assert "node-1" not in allow.values()


def test_readd_rotates_single_cert(tmp_path):
    d = str(tmp_path)
    nodecli.main(["init", "--dir", d])
    nodecli.main(["add", "n", "--dir", d])
    nodecli.main(["add", "n", "--dir", d])               # re-add must not pile up certs
    allow = json.load(open(os.path.join(d, "allowlist.json")))
    assert list(allow.values()).count("n") == 1


def test_list_shows_registered(tmp_path, capsys):
    d = str(tmp_path)
    nodecli.main(["init", "--dir", d])
    nodecli.main(["add", "alpha", "--dir", d])
    capsys.readouterr()                                   # drop the add output
    nodecli.main(["list", "--dir", d])
    assert "alpha" in capsys.readouterr().out

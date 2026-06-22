from bot.nodes import NodeRegistry, should_offload


def test_offload_decision():
    r = NodeRegistry(heartbeat_ttl=30)
    assert should_offload(True, r) is False        # busy, but no live node -> local
    r.ping("n1")
    assert should_offload(True, r) is True          # busy + a live node -> offload
    assert should_offload(False, r) is False        # free slot -> always local


def test_stale_node_not_alive():
    r = NodeRegistry(heartbeat_ttl=0)               # ttl 0 -> nothing counts as alive
    r.ping("n1")
    assert r.alive() is False


def test_claim_is_atomic_and_oldest_first():
    r = NodeRegistry()
    r.enqueue("j1", "/tmp/j1.zip", "rec1")
    r.enqueue("j2", "/tmp/j2.zip", "rec2")
    assert r.claim("n1")["job_id"] == "j1"          # oldest first
    assert r.claim("n1")["job_id"] == "j2"
    assert r.claim("n1") is None                     # queue drained


def test_result_and_progress_roundtrip():
    r = NodeRegistry()
    r.enqueue("j1", "/tmp/j1.zip", "rec1")
    r.claim("n1")
    r.set_progress("j1", "encode", 50)
    assert r.get_progress("j1") == ("encode", 50)
    r.set_result("j1", "/tmp/out.mp4")
    assert r.pop_result("j1") == "/tmp/out.mp4"
    assert r.pop_result("j1") is None                # consumed once


def test_expired_claim_is_returned_for_requeue():
    r = NodeRegistry(claim_ttl=0)                    # claims expire immediately
    r.enqueue("j1", "/tmp/j1.zip", "rec1")
    r.claim("n1")
    exp = r.expired()
    assert [j["job_id"] for j in exp] == ["j1"]
    assert r.expired() == []                          # removed after being handed back


def test_allowlist():
    r = NodeRegistry()
    assert r.is_allowed("ab12") is False
    r.allow("ab12", "n1")
    assert r.is_allowed("ab12") is True

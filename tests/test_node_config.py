import importlib


def test_node_config_safe_defaults(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "123:abc")  # config refuses to import without it
    for k in ("NODE_API_ENABLE", "NODE_API_PORT", "NODE_API_HOST", "NODE_DIR",
              "HEARTBEAT_TTL", "CLAIM_TTL"):
        monkeypatch.delenv(k, raising=False)
    from bot import config
    importlib.reload(config)
    assert config.NODE_API_ENABLE is None       # unset -> auto (resolved in main from the allowlist)
    assert config.NODE_API_PORT == 8443
    assert config.NODE_DIR == "nodes"
    assert config.HEARTBEAT_TTL == 30
    assert config.CLAIM_TTL == 1200

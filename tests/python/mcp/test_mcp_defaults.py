from src.config.mcp import McpConfig


def test_mcp_defaults_hold_off_and_server_on():
    cfg = McpConfig()
    assert cfg.gate_cross_session_actions is False
    assert cfg.enabled is True

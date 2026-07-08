"""wesktop's agent role registry (moved here from fastware).

The framework (fastware.mcp) is role-agnostic; the implementor/auditor/
reviewer/deployer domain model is wesktop's. These tests guard the registry
shape and the re-exported fastware factories.
"""

from types import ModuleType

import pytest

from wesktop.mcp import DEFAULT_ROLE, ROLES, register_tools_for_role


def test_roles_importable():
    """ROLES and DEFAULT_ROLE are importable from wesktop.mcp."""
    assert isinstance(ROLES, dict)
    assert "implementor" in ROLES
    assert "auditor" in ROLES
    assert "reviewer" in ROLES
    assert "deployer" in ROLES
    assert DEFAULT_ROLE == "auditor"


def test_roles_importable_from_top_level():
    """ROLES/DEFAULT_ROLE and the factories are in wesktop's public API."""
    import wesktop

    assert wesktop.ROLES is ROLES
    assert wesktop.DEFAULT_ROLE == "auditor"
    assert callable(wesktop.create_mcp_server)
    assert callable(wesktop.register_tools_for_role)


def test_role_tool_sets():
    """Each role has a 'tools' list and a 'level' string."""
    for name, config in ROLES.items():
        assert "level" in config, f"Role {name} missing 'level'"
        assert "tools" in config, f"Role {name} missing 'tools'"
        assert isinstance(config["tools"], list)
        assert len(config["tools"]) > 0


def test_implementor_has_write_tools():
    impl_tools = ROLES["implementor"]["tools"]
    assert "write_file" in impl_tools
    assert "edit_file" in impl_tools
    assert "git_commit" in impl_tools


def test_auditor_lacks_write_tools():
    aud_tools = ROLES["auditor"]["tools"]
    assert "write_file" not in aud_tools
    assert "edit_file" not in aud_tools
    assert "git_commit" not in aud_tools


def test_reviewer_has_post_review_comment():
    assert "post_review_comment" in ROLES["reviewer"]["tools"]


def test_deployer_has_pipeline_tools():
    dep_tools = ROLES["deployer"]["tools"]
    assert "stage_branch" in dep_tools
    assert "create_prod_pr" in dep_tools
    assert "check_pipeline" in dep_tools


def test_all_roles_have_ask_user():
    for name, config in ROLES.items():
        assert "ask_user" in config["tools"], f"Role {name} missing ask_user"


def test_register_tools_with_wesktop_roles():
    """fastware's role-agnostic registrar works with wesktop's ROLES."""
    mod = ModuleType("fake_tools")
    mod.TOOLS = {
        "read_file": lambda: "read",
        "write_file": lambda: "write",
    }

    registered = {}

    class FakeServer:
        def add_tool(self, fn, *, name):
            registered[name] = fn

    result = register_tools_for_role(
        FakeServer(), "auditor", [mod], roles=ROLES, default_role=DEFAULT_ROLE
    )
    assert "read_file" in result
    assert "write_file" not in result


def test_create_mcp_server_missing_package_is_hard_error(monkeypatch):
    """create_mcp_server raises RuntimeError when the mcp package is absent."""
    import fastware.mcp as fastware_mcp

    monkeypatch.setattr(fastware_mcp, "_MCP_AVAILABLE", False)
    from wesktop.mcp import create_mcp_server

    with pytest.raises(RuntimeError, match="mcp.*package.*required"):
        create_mcp_server()

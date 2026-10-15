"""AT0.4 - tenant -> graph name mapping and input validation."""

from __future__ import annotations

import pytest

from pedigree.config import (
    REGISTRY_GRAPH,
    checkpoint_graph_name,
    default_integrity,
    graph_name,
    validate_artifact,
    validate_id,
    whatif_graph_name,
)
from pedigree.errors import InvalidArgument


def test_graph_name_valid():
    assert graph_name("abc") == "ped:abc"
    assert graph_name("a1" * 12) == "ped:" + "a1" * 12  # 24 chars
    assert graph_name("t0123456789") == "ped:t0123456789"


@pytest.mark.parametrize("bad", ["ab", "ABC", "a_b", "abc:x", "a" * 25, "", None, 123, "ab ", " ab", "abc\n", "ped:abc"])
def test_graph_name_invalid(bad):
    with pytest.raises(InvalidArgument):
        graph_name(bad)  # type: ignore[arg-type]


def test_registry_graph_name_is_fixed():
    assert REGISTRY_GRAPH == "pedigree:registry"


def test_whatif_and_checkpoint_names():
    assert whatif_graph_name("abc", "deadbeef") == "ped:abc:wi:deadbeef"
    assert checkpoint_graph_name("abc", "demo1") == "ped:abc:ck:demo1"
    for bad_token in ["DEADBEEF", "deadbee", "deadbeef0", "dead beef", ""]:
        with pytest.raises(InvalidArgument):
            whatif_graph_name("abc", bad_token)
    for bad_name in ["", "UPPER", "with space", "a" * 40, "-lead"]:
        with pytest.raises(InvalidArgument):
            checkpoint_graph_name("abc", bad_name)


def test_ids_allow_underscore_and_path_chars():
    assert validate_id("src_deadbeef") == "src_deadbeef"
    assert validate_id("m1") == "m1"
    assert validate_id("a:c/1.2@3#4-5_6") == "a:c/1.2@3#4-5_6"
    for bad in ["", "a" * 129, "with space", "semi;colon", None, 42]:
        with pytest.raises(InvalidArgument):
            validate_id(bad)  # type: ignore[arg-type]


def test_artifacts_allow_windows_paths_and_urls():
    assert validate_artifact(r"C:\Users\vedan\Documents\Pedigree\README.md")
    assert validate_artifact("https://example.com/a?b=c#d")
    assert validate_artifact("a" * 512)
    for bad in ["", "a" * 513, "tab\tchar", None]:
        with pytest.raises(InvalidArgument):
            validate_artifact(bad)  # type: ignore[arg-type]


def test_default_integrity_by_kind():
    assert default_integrity("web") == "untrusted"
    assert default_integrity("tool_output") == "untrusted"
    assert default_integrity("mcp_tool_desc") == "untrusted"
    assert default_integrity("user_prompt") == "trusted"
    assert default_integrity("file") == "trusted"
    assert default_integrity("rules_file") == "trusted"

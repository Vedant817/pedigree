"""Unit tests for the gate's pure logic (F-11).

No database here: verdict mapping, reason building, the `policy.yaml` classifier table,
audience defaults, and the Claude Code hook mapping.
"""
from __future__ import annotations

import pytest

from pedigree.config import EFFECTS, RISKS
from pedigree.engine.gate import (
    HOOK_MAP,
    SEVERITY,
    TRUSTED_SUPPORT,
    Policy,
    classify_action,
    default_audience,
    hook_output,
    load_policy,
    risk_blocks,
)

# --- classifier (docs/01 section 7.3) ---------------------------------------

@pytest.mark.parametrize("tool,summary,effect,risk", [
    ("Bash", "git push origin main", "irreversible", "high"),
    ("Bash", "npm publish", "irreversible", "high"),
    ("Bash", "cargo publish --registry crates-io", "irreversible", "high"),
    ("Bash", "docker push registry/img:1", "irreversible", "high"),
    ("Bash", "kubectl apply -f deploy.yaml", "irreversible", "high"),
    ("Bash", "terraform apply", "irreversible", "high"),
    ("Bash", "ssh prod 'rm -rf /'", "irreversible", "high"),
    ("Bash", "scp a b", "irreversible", "high"),
    ("Bash", "/usr/bin/ssh host", "irreversible", "high"),
    ("Bash", "FOO=1 sudo -n true", "irreversible", "high"),
    ("Bash", "sudo apt install x", "irreversible", "high"),
    ("Bash", "cat ~/.ssh/config", "reversible", "low"),
    ("Bash", "head ~/.ssh/authorized_keys", "reversible", "low"),
    ("Bash", "echo ssh is not a command", "reversible", "low"),
    ("Bash", "echo curl -X POST https://example.com", "reversible", "low"),
    ("Bash", "git commit -m wip && git push", "irreversible", "high"),
    ("Bash", "rm -rf build/", "irreversible", "high"),
    ("Bash", "curl -X POST https://x/api", "irreversible", "high"),
    ("Bash", "git commit -m 'wip'", "reversible", "medium"),
    ("Bash", "ls -la", "reversible", "low"),
    ("Edit", "src/main.py", "reversible", "low"),
    ("WebFetch", "https://example.com", "reversible", "low"),
    ("webfetch", "https://example.com/docs", "reversible", "low"),
    ("unknown_tool", "", "reversible", "low"),
])
def test_classifier_table(tool, summary, effect, risk):
    policy = load_policy(None)  # built-in defaults
    assert classify_action(policy, tool, summary) == (effect, risk)


def test_classifier_explicit_effect_and_risk_win_over_table():
    policy = load_policy(None)
    assert classify_action(policy, "Bash", "ls", effect="irreversible", risk="high") == (
        "irreversible", "high")


def test_classifier_rejects_junk_and_falls_back():
    policy = load_policy(None)
    assert classify_action(policy, "Bash", "ls", effect="banana", risk="extreme") == (
        "reversible", "low")


# --- audience defaults (docs/01 section 6.6) --------------------------------

@pytest.mark.parametrize("tool", ["Bash", "WebFetch", "webfetch", "WebSearch", "bash"])
def test_audience_defaults_public_for_network_tools(tool):
    policy = load_policy(None)
    assert default_audience(policy, tool) == ["public"]


@pytest.mark.parametrize("tool", ["Edit", "Read", "grep", "ls", ""])
def test_audience_defaults_local_otherwise(tool):
    policy = load_policy(None)
    assert default_audience(policy, tool) == ["local"]


# --- verdict severity --------------------------------------------------------

def test_risk_blocks_only_at_medium_and_high():
    assert risk_blocks("low") is False
    assert risk_blocks("medium") is True
    assert risk_blocks("high") is True
    assert SEVERITY["allow"] < SEVERITY["warn"] < SEVERITY["reverify"] < SEVERITY["block"]


def test_trusted_support_values():
    assert TRUSTED_SUPPORT == frozenset({"human", "scanner"})


# --- hook mapping (docs/01 section 8.1) --------------------------------------

def test_hook_mapping_claude_code_values():
    assert HOOK_MAP["block"] == "deny"
    assert HOOK_MAP["reverify"] == "ask"
    assert HOOK_MAP["warn"] == "allow"
    assert HOOK_MAP["allow"] == "allow"


def test_hook_output_shape_for_pre_tool_use():
    out = hook_output("block", "mem_1 is tainted")
    assert out["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "mem_1 is tainted" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_hook_output_allow_has_no_decision_field():
    out = hook_output("allow", "")
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"


# --- policy loading ----------------------------------------------------------

def test_missing_policy_file_falls_back_to_defaults(tmp_path):
    policy = load_policy(str(tmp_path / "nope.yaml"))
    assert classify_action(policy, "Bash", "git push") == ("irreversible", "high")


def test_invalid_policy_yaml_falls_back_to_defaults(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("::: not yaml :::\n\t- broken", encoding="utf-8")
    policy = load_policy(str(p))
    assert isinstance(policy, Policy)
    assert classify_action(policy, "Bash", "git push") == ("irreversible", "high")


def test_custom_policy_rule_overrides_table(tmp_path):
    p = tmp_path / "policy.yaml"
    p.write_text(
        "rules:\n"
        "  - tool: 'Bash'\n"
        "    match: 'git push'\n"
        "    effect: reversible\n"
        "    risk: low\n",
        encoding="utf-8",
    )
    policy = load_policy(str(p))
    assert classify_action(policy, "Bash", "git push origin main") == ("reversible", "low")
    # unrelated commands still use the built-in table
    assert classify_action(policy, "Bash", "ls") == ("reversible", "low")


def test_policy_rule_values_are_validated(tmp_path):
    p = tmp_path / "policy.yaml"
    p.write_text(
        "rules:\n  - tool: 'Bash'\n    match: 'x'\n    effect: nonsense\n    risk: extreme\n",
        encoding="utf-8",
    )
    policy = load_policy(str(p))
    effect, risk = classify_action(policy, "Bash", "x")
    assert effect in EFFECTS and risk in RISKS

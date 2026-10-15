"""Unit tests for engine/blame.py pure helpers (no FalkorDB required)."""

from __future__ import annotations

import pytest

from pedigree.engine.blame import _norm_depth, bfs_paths
from pedigree.errors import InvalidArgument


def test_norm_depth_minimum_and_maximum():
    assert _norm_depth(1) == 1
    assert _norm_depth(12) == 12
    assert _norm_depth(999) == 12


def test_norm_depth_rejects_zero_and_negatives():
    with pytest.raises(InvalidArgument):
        _norm_depth(0)
    with pytest.raises(InvalidArgument):
        _norm_depth(-5)


def test_norm_depth_rejects_bool_and_non_int():
    with pytest.raises(InvalidArgument):
        _norm_depth(True)
    with pytest.raises(InvalidArgument):
        _norm_depth(3.5)
    with pytest.raises(InvalidArgument):
        _norm_depth("7")


def test_bfs_paths_on_a_diamond():
    parents = {
        "A": ["B", "C"],
        "B": ["D"],
        "C": ["D"],
        "D": [],
    }
    out = bfs_paths(parents, "A", ["D"])
    assert out["D"] == ["A", "B", "D"] or out["D"] == ["A", "C", "D"]


def test_bfs_paths_multiple_targets():
    parents = {"A": ["B", "C"], "B": ["D"], "C": ["E"], "D": [], "E": []}
    out = bfs_paths(parents, "A", ["D", "E", "Z"])
    assert out["D"] == ["A", "B", "D"]
    assert out["E"] == ["A", "C", "E"]
    assert out["Z"] is None


def test_bfs_paths_depth_cap():
    parents = {"A": ["B"], "B": ["C"], "C": ["D"], "D": []}
    out = bfs_paths(parents, "A", ["D"], limit=2)
    assert out["D"] is None
    out = bfs_paths(parents, "A", ["D"], limit=3)
    assert out["D"] == ["A", "B", "C", "D"]


def test_bfs_paths_self_target():
    out = bfs_paths({}, "A", ["A"])
    assert out["A"] == ["A"]

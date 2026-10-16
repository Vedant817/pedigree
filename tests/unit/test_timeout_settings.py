"""Timeout validation must stay within the pinned server limit without import warnings."""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from pedigree.config import Settings


@pytest.fixture(autouse=True)
def clean_settings_environment(monkeypatch):
    for name in list(os.environ):
        if name.lower() in Settings.model_fields:
            monkeypatch.delenv(name)


def test_configuration_import_has_no_overridden_validator_warning():
    result = subprocess.run(
        [sys.executable, "-W", "error::UserWarning", "-c", "import pedigree.config"],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("field", ["read_timeout_ms", "write_timeout_ms"])
@pytest.mark.parametrize("value", [-1, 0, 60001])
def test_timeout_outside_server_bounds_rejected(field, value):
    with pytest.raises(ValidationError, match=field):
        Settings(_env_file=None, **{field: value})


@pytest.mark.parametrize("field", ["read_timeout_ms", "write_timeout_ms"])
@pytest.mark.parametrize("value", [1, 60000])
def test_timeout_exact_server_bounds_accepted(field, value):
    assert getattr(Settings(_env_file=None, **{field: value}), field) == value

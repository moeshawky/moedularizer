"""G-HALL: Test that CLI module imports correctly."""

import pytest

pytestmark = pytest.mark.smoke


def test_cli_import():
    """Verify cli.py can be imported without errors."""
    from moedularizer import cli

    assert cli is not None
    assert hasattr(cli, "main")


def test_cli_symbolkind_import():
    """Verify SymbolKind is imported in cli.py (catches import errors)."""
    # This test will fail if SymbolKind is not imported in cli.py
    from moedularizer.cli import SymbolKind

    assert SymbolKind is not None

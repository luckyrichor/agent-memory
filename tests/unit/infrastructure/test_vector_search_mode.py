"""B3: the mode decision is a version check, because the GUC is invisible before the library loads."""
import pytest

from agent_memory.infrastructure.retrieval import supports_iterative_scan


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("0.8.0", True),
        ("0.8.6", True),
        ("0.9.1", True),
        ("1.0.0", True),
        ("0.7.4", False),
        ("0.6.0", False),
        ("", False),
        (None, False),
        ("not-a-version", False),
    ],
)
def test_iterative_scan_needs_pgvector_08(version, expected) -> None:
    assert supports_iterative_scan(version) is expected

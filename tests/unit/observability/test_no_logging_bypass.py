"""A source boundary: only the telemetry adapter may import logging."""
import ast
from pathlib import Path


def violations(source: str) -> list[int]:
    tree = ast.parse(source)
    return [node.lineno for node in ast.walk(tree) if (
        isinstance(node, ast.Import) and any(a.name == "logging" or a.name.startswith("logging.")
                                            for a in node.names)
    ) or (isinstance(node, ast.ImportFrom) and node.module is not None and
          (node.module == "logging" or node.module.startswith("logging.")))]


def test_application_cannot_import_raw_logging() -> None:
    root = Path("src/agent_memory")
    bad = {str(p): violations(p.read_text()) for p in root.rglob("*.py")
           if "observability" not in p.parts and violations(p.read_text())}
    assert bad == {}


def test_guard_detects_aliases_and_from_imports() -> None:
    assert violations("import logging as innocent\nfrom logging import getLogger as safe") == [1, 2]

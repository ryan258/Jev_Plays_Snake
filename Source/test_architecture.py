"""Checks the shape of the code: modules may only use modules in LOWER layers.

Run from this directory:  python3 -m unittest -v test_architecture

If this fails, a module reached "up" to a higher layer. Move the shared piece down
into a lower module instead of adding the import. The map is in snakebot/__init__.py.
"""

import ast
import unittest
from pathlib import Path

PKG = Path(__file__).parent / "snakebot"

# Lower number = lower layer. A module may import only from a lower layer
# (or, inside the players package, from another module on the same layer).
LAYER = {
    "config": 0, "geometry": 0, "prompts": 0, "tmuxio": 0,
    "env": 1, "screen": 1, "pathfinding": 1,
    "guard": 2, "players.wire": 2, "players.models": 2,
    "players.base": 3, "players.jev": 3, "players.openrouter": 3, "players.algorithm": 3,
    "players": 4, "report": 4,
    "runlog": 5,
    "runner": 6,
    "launcher": 7,
    "cli": 8,
}


def module_name(path):
    """snakebot/players/jev.py -> "players.jev"; snakebot/players/__init__.py -> "players"."""
    parts = list(path.relative_to(PKG).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def internal_imports(path):
    """The snakebot modules this file imports, as names like "config" or "players.models"."""
    mod = module_name(path)
    package = mod.split(".")[:-1] if path.name != "__init__.py" else mod.split(".")
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.level:
            base = package[: len(package) - (node.level - 1)]
            target = ".".join(base + (node.module.split(".") if node.module else []))
            if target in LAYER:
                found.add(target)
            else:  # "from . import name" style: each imported name may be a module
                found.update(f"{target}.{a.name}" for a in node.names if f"{target}.{a.name}" in LAYER)
    return found


class ArchitectureTests(unittest.TestCase):
    def test_every_module_has_a_layer(self):
        modules = {module_name(p) for p in PKG.rglob("*.py")} - {""}
        self.assertEqual(modules, set(LAYER), "add new modules to LAYER (and to snakebot/__init__.py)")

    def test_modules_only_use_lower_layers(self):
        problems = []
        for path in PKG.rglob("*.py"):
            mod = module_name(path)
            if not mod:
                continue
            for dep in internal_imports(path):
                same_package = "." in mod and "." in dep and mod.split(".")[0] == dep.split(".")[0]
                ok = LAYER[dep] < LAYER[mod] or (same_package and LAYER[dep] == LAYER[mod] and dep != mod)
                if not ok:
                    problems.append(f"{mod} (layer {LAYER[mod]}) imports {dep} (layer {LAYER[dep]})")
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Optional Kotlin grammar validation. Does not resolve types or Android APIs."""
from pathlib import Path
from tree_sitter import Language, Parser
import tree_sitter_kotlin

root = Path(__file__).resolve().parents[1]
parser = Parser(Language(tree_sitter_kotlin.language()))
files = list(root.rglob('*.kt')) + list(root.rglob('*.kts'))
errors = []
for path in files:
    data = path.read_bytes()
    tree = parser.parse(data)
    def visit(node):
        if node.type == 'ERROR' or node.is_missing:
            errors.append(f'{path.relative_to(root)}:{node.start_point.row+1}:{node.start_point.column+1} {node.type}')
        for child in node.children:
            visit(child)
    visit(tree.root_node)
print(f'KOTLIN_SYNTAX_ONLY: {len(files)} files, {len(errors)} grammar errors. NOT a Kotlin compilation.')
for error in errors:
    print(error)
raise SystemExit(bool(errors))

from __future__ import annotations

import ast
from collections.abc import Mapping
from pathlib import Path


class JsonStructureError(RuntimeError):
    path: Path
    detail: str

    def __init__(self, path: Path, detail: str) -> None:
        self.path = path
        self.detail = detail
        super().__init__(f"Invalid JSON document: {path}: {detail}")


def json_node_object(node: ast.expr) -> Mapping[str, ast.expr]:
    if not isinstance(node, ast.Dict):
        return {}
    values: dict[str, ast.expr] = {}
    for key_node, value_node in zip(node.keys, node.values):
        if not isinstance(key_node, ast.Constant):
            continue
        key = key_node.value
        if isinstance(key, str):
            values[key] = value_node
    return values


def json_object_document(content: str, path: Path) -> Mapping[str, ast.expr]:
    try:
        expression = ast.parse(content, mode="eval")
    except (SyntaxError, ValueError) as error:
        raise JsonStructureError(path, str(error)) from error
    values = json_node_object(expression.body)
    if not values and content.strip() != "{}":
        raise JsonStructureError(path, "top-level value must be an object")
    return values


def json_node_string(node: ast.expr | None) -> str | None:
    if not isinstance(node, ast.Constant):
        return None
    value = node.value
    return value if isinstance(value, str) else None


def json_node_integer(node: ast.expr | None) -> int | None:
    if not isinstance(node, ast.Constant):
        return None
    value = node.value
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def json_node_boolean(node: ast.expr | None) -> bool | None:
    if isinstance(node, ast.Name):
        if node.id == "true":
            return True
        if node.id == "false":
            return False
    if not isinstance(node, ast.Constant):
        return None
    value = node.value
    return value if isinstance(value, bool) else None


def json_node_is_null(node: ast.expr | None) -> bool:
    return (
        isinstance(node, ast.Name)
        and node.id == "null"
        or (isinstance(node, ast.Constant) and node.value is None)
    )


def json_node_string_list(node: ast.expr | None) -> list[str]:
    if not isinstance(node, (ast.List, ast.Tuple)):
        return []
    values: list[str] = []
    for element in node.elts:
        value = json_node_string(element)
        if value is not None:
            values.append(value)
    return values

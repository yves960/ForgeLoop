from __future__ import annotations

import ast
from pathlib import Path
from typing import Literal, TypedDict

from structured_json import (
    JsonStructureError,
    json_node_boolean,
    json_node_integer,
    json_node_object,
    json_node_string,
    json_node_string_list,
    json_object_document,
)


class CompletionPolicy(TypedDict, total=False):
    requireVerifierPass: bool


class VerifierProfile(TypedDict, total=False):
    type: Literal["java-ut", "maven"]
    arguments: list[str]
    passReason: str
    failReason: str
    requiredOutputPatterns: list[str]


class EngineeringProfile(TypedDict, total=False):
    name: str
    description: str
    defaultMaxIterations: int
    allowedPathSuffixes: list[str]
    forbiddenAddedPatterns: list[str]
    requiredPaths: list[str]
    verifier: VerifierProfile
    completion: CompletionPolicy


class ProfileReadError(RuntimeError):
    path: Path
    detail: str

    def __init__(self, path: Path, detail: str) -> None:
        self.path = path
        self.detail = detail
        super().__init__(f"Invalid engineering profile: {path}: {detail}")


class UnknownProfileError(RuntimeError):
    name: str

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Unknown profile: {name}")


def parse_engineering_profile(
    node: ast.expr,
    path: Path,
) -> EngineeringProfile:
    values = json_node_object(node)
    if not values:
        raise ProfileReadError(path, "profile must be an object")

    profile = EngineeringProfile()
    for key in ("name", "description"):
        value = json_node_string(values.get(key))
        if value is not None:
            profile[key] = value

    maximum = json_node_integer(values.get("defaultMaxIterations"))
    if maximum is not None:
        profile["defaultMaxIterations"] = maximum

    for key in ("allowedPathSuffixes", "forbiddenAddedPatterns", "requiredPaths"):
        if key in values:
            profile[key] = json_node_string_list(values.get(key))

    verifier_node = values.get("verifier")
    if verifier_node is not None:
        verifier_values = json_node_object(verifier_node)
        verifier = VerifierProfile()
        verifier_type = json_node_string(verifier_values.get("type"))
        if verifier_type == "java-ut" or verifier_type == "maven":
            verifier["type"] = verifier_type
        elif verifier_type is not None:
            raise ProfileReadError(path, f"unsupported verifier type: {verifier_type}")
        if "arguments" in verifier_values:
            verifier["arguments"] = json_node_string_list(
                verifier_values.get("arguments")
            )
        if "requiredOutputPatterns" in verifier_values:
            verifier["requiredOutputPatterns"] = json_node_string_list(
                verifier_values.get("requiredOutputPatterns")
            )
        for key in ("passReason", "failReason"):
            value = json_node_string(verifier_values.get(key))
            if value is not None:
                verifier[key] = value
        profile["verifier"] = verifier

    completion_node = values.get("completion")
    if completion_node is not None:
        completion_values = json_node_object(completion_node)
        completion = CompletionPolicy()
        required = json_node_boolean(completion_values.get("requireVerifierPass"))
        if required is not None:
            completion["requireVerifierPass"] = required
        profile["completion"] = completion
    return profile


def load_engineering_profile(
    profiles_dir: Path,
    name: str,
) -> EngineeringProfile:
    path = profiles_dir / name / "profile.json"
    if not path.exists():
        raise UnknownProfileError(name)
    try:
        values = json_object_document(path.read_text(encoding="utf-8"), path)
    except (OSError, UnicodeError, JsonStructureError) as error:
        detail = error.detail if isinstance(error, JsonStructureError) else str(error)
        raise ProfileReadError(path, detail) from error

    expression = ast.Dict(
        keys=[ast.Constant(key) for key in values],
        values=list(values.values()),
    )
    return parse_engineering_profile(expression, path)

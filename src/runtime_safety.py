from __future__ import annotations

from pathlib import Path


class UnsafeRuntimePathError(RuntimeError):
    path: Path

    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(f"Runtime directory contains a symbolic link: {path}")


def validate_runtime_directory(module_dir: Path, name: str) -> Path:
    module_root = module_dir.resolve()
    runtime_dir = module_dir / name
    if runtime_dir.is_symlink() or not runtime_dir.is_dir():
        raise UnsafeRuntimePathError(runtime_dir)
    try:
        _ = runtime_dir.resolve().relative_to(module_root)
    except ValueError as error:
        raise UnsafeRuntimePathError(runtime_dir) from error
    linked_path = next(
        (path for path in runtime_dir.rglob("*") if path.is_symlink()), None
    )
    if linked_path is not None:
        raise UnsafeRuntimePathError(linked_path)
    return runtime_dir


def prepare_runtime_directory(module_dir: Path, name: str) -> Path:
    runtime_path = module_dir / name
    if runtime_path.is_symlink():
        raise UnsafeRuntimePathError(runtime_path)
    runtime_path.mkdir(parents=False, exist_ok=True)
    return validate_runtime_directory(module_dir, name)


def prepare_verifier_directory(module_dir: Path, iteration_dir: Path) -> Path:
    runtime_dir = prepare_runtime_directory(module_dir, ".loop")
    try:
        relative_iteration = iteration_dir.relative_to(runtime_dir)
    except ValueError as error:
        raise UnsafeRuntimePathError(iteration_dir) from error
    target = runtime_dir / relative_iteration
    target.mkdir(parents=True, exist_ok=True)
    _ = validate_runtime_directory(module_dir, ".loop")
    return target

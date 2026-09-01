"""Load bounded, UTF-8 YAML mappings through a duplicate-key-safe loader."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """SafeLoader variant that rejects duplicate mapping keys at every level."""

    def construct_mapping(
        self,
        node: yaml.MappingNode,
        deep: bool = False,
    ) -> dict[Any, Any]:
        if not isinstance(node, yaml.MappingNode):
            raise yaml.constructor.ConstructorError(
                None,
                None,
                "expected a mapping node",
                node.start_mark,
            )

        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if type(key) is not str:
                raise ValueError("YAML mapping keys must be strings")
            if key in mapping:
                raise ValueError("duplicate YAML mapping key")
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def load_yaml_document(path: Path, *, max_bytes: int = 1_048_576) -> dict[str, object]:
    """Read one bounded UTF-8 YAML mapping with safe construction semantics."""

    if type(max_bytes) is not int or max_bytes < 0:
        raise ValueError("max_bytes must be a non-negative strict integer")

    raw = path.read_bytes()
    if len(raw) > max_bytes:
        raise ValueError("YAML document exceeds the size limit")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError("UTF-8 BOM is not permitted")

    text = raw.decode("utf-8", errors="strict")
    value = yaml.load(text, Loader=_UniqueKeySafeLoader)
    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        raise ValueError("YAML document root must be a mapping with string keys")
    return cast(dict[str, object], value)

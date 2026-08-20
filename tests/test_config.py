from typing import Any

import pytest
from pydantic import ValidationError

from neontof.config import ContractModel, ServerOptions, load_server_options


def test_load_server_options_uses_only_allowed_environment_keys() -> None:
    options = load_server_options(
        {
            "NEONTOF_HOST": "localhost",
            "NEONTOF_PORT": "9000",
            "NEONTOF_WORKERS": "1",
            "UNUSED_CONFIGURATION": "ignored",
        }
    )

    assert options == ServerOptions(host="localhost", port=9000, workers=1)


def test_load_server_options_defaults_are_local_single_worker() -> None:
    assert load_server_options({}) == ServerOptions(host="127.0.0.1", port=8765, workers=1)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("NEONTOF_HOST", ""),
        ("NEONTOF_PORT", "0"),
        ("NEONTOF_PORT", "65536"),
        ("NEONTOF_PORT", "not-an-integer"),
        ("NEONTOF_WORKERS", "0"),
        ("NEONTOF_WORKERS", "2"),
    ],
)
def test_load_server_options_rejects_invalid_values(key: str, value: str) -> None:
    with pytest.raises(ValueError):
        load_server_options({key: value})


def test_contract_model_is_strict_forbid_and_frozen() -> None:
    from neontof.contracts import base as contracts_base

    from neontof import app as app_module

    assert ContractModel.model_config["strict"] is True
    assert ContractModel.model_config["extra"] == "forbid"
    assert ContractModel.model_config["frozen"] is True
    assert ContractModel.model_config["revalidate_instances"] == "always"
    assert ContractModel is contracts_base.ContractModel
    assert app_module.ContractModel is contracts_base.ContractModel

    with pytest.raises(ValidationError):
        ServerOptions.model_validate({"host": "127.0.0.1", "port": "8765"})
    with pytest.raises(ValidationError):
        ServerOptions.model_validate({"host": "127.0.0.1", "port": 8765, "unexpected": "rejected"})

    options = ServerOptions(host="127.0.0.1", port=8765)
    with pytest.raises(ValidationError):
        field_name = "port"
        setattr(options, field_name, 9000)


def test_server_options_has_no_mutable_public_fields() -> None:
    fields: dict[str, Any] = ServerOptions.model_fields

    assert tuple(fields) == ("host", "port", "workers")
    assert all(field.annotation not in (list, dict) for field in fields.values())

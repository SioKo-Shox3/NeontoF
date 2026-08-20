"""P0-03 modelのstrictnessとimmutabilityに関するcanonical契約テスト。"""

from operator import setitem
from typing import Any

import pytest
from pydantic import StrictInt, TypeAdapter, ValidationError


def test_contract_model_is_strict_forbid_frozen_and_revalidates_instances() -> None:
    from neontof.contracts.base import ContractModel

    class SampleModel(ContractModel):
        count: StrictInt

    assert ContractModel.model_config["strict"] is True
    assert ContractModel.model_config["extra"] == "forbid"
    assert ContractModel.model_config["frozen"] is True
    assert ContractModel.model_config["revalidate_instances"] == "always"
    assert SampleModel.model_config == ContractModel.model_config

    with pytest.raises(ValidationError):
        SampleModel.model_validate({"count": "1"})
    with pytest.raises(ValidationError):
        SampleModel.model_validate({"count": 1, "unexpected": "field"})

    sample = SampleModel(count=1)
    with pytest.raises(ValidationError):
        sample.count = 2

    object.__setattr__(sample, "count", "sabotaged")
    with pytest.raises(ValidationError):
        SampleModel.model_validate(sample)


def test_frozen_json_is_tuple_based_sorted_and_alias_disconnected() -> None:
    from neontof.contracts.base import FrozenJsonValue

    nested_object: dict[str, object] = {"nested": 1}
    nested_array: list[object] = [nested_object]
    source: dict[str, object] = {"z": nested_array, "a": True}
    adapter = TypeAdapter(FrozenJsonValue)

    value = adapter.validate_python(source, strict=True)

    assert value == (("a", True), ("z", ((("nested", 1),),)))
    assert isinstance(value, tuple)
    assert isinstance(value[0], tuple)

    nested_object["nested"] = 99
    nested_array.append("mutated")
    source["z"] = []
    assert value == (("a", True), ("z", ((("nested", 1),),)))

    nested_value = value[1]
    assert isinstance(nested_value, tuple)
    immutable_value: Any = value
    immutable_nested_value: Any = nested_value
    with pytest.raises(TypeError):
        setitem(immutable_value, 0, ("replaced", None))
    with pytest.raises(TypeError):
        setitem(immutable_nested_value, 0, (("replaced", None),))


def test_frozen_json_rejects_nonfinite_float_and_bool_as_strict_int() -> None:
    from neontof.contracts.base import FrozenJsonValue

    json_adapter = TypeAdapter(FrozenJsonValue)
    strict_int_adapter = TypeAdapter(StrictInt)

    for invalid in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValidationError):
            json_adapter.validate_python(invalid, strict=True)

    assert strict_int_adapter.validate_python(7, strict=True) == 7
    with pytest.raises(ValidationError):
        strict_int_adapter.validate_python(True, strict=True)


def test_nested_contract_models_are_immutable_and_forbid_extra_fields() -> None:
    from neontof.contracts.base import ContractModel, FrozenJsonValue

    class NestedModel(ContractModel):
        value: FrozenJsonValue

    model = NestedModel.model_validate({"value": {"answer": 42}})
    with pytest.raises(ValidationError):
        model.value = (("answer", 7),)
    with pytest.raises(ValidationError):
        NestedModel.model_validate({"value": {"answer": 42}, "extra": True})

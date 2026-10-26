# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

from isaaclab_arena.assets.asset_definition import AssetDefinition, AssetKind
from isaaclab_arena.assets.object_type import ObjectType
from isaaclab_arena.assets.registries import AssetRegistry


class _DummyAsset:
    registry_name = "dummy"
    tags = ["object", "test"]
    object_type = ObjectType.RIGID
    usd_path = "/dummy.usd"

    def __init__(self, name: str = "dummy", settings: dict | None = None):
        self.name = name
        self.settings = settings


def _isolated_asset_registry(monkeypatch) -> AssetRegistry:
    from isaaclab_arena.assets import registries

    monkeypatch.setattr(registries, "ensure_assets_registered", lambda: None)
    registry = object.__new__(AssetRegistry)
    registry._components = {}
    return registry


def test_definition_from_factory_preserves_catalogue_metadata():
    definition = AssetDefinition.from_factory(_DummyAsset)

    assert definition.registry_name == "dummy"
    assert definition.tags == ("object", "test")
    assert definition.asset_kind is AssetKind.OBJECT
    assert definition.object_type is ObjectType.RIGID
    assert definition.resolve_usd_path() == "/dummy.usd"


def test_definition_copies_mutable_defaults_for_each_asset():
    definition = AssetDefinition(
        registry_name="native_dummy",
        factory=_DummyAsset,
        tags=("object",),
        asset_kind=AssetKind.OBJECT,
        object_type=ObjectType.RIGID,
        default_params={"settings": {"values": []}},
    )

    first = definition.create(name="first")
    second = definition.create(name="second")
    first.settings["values"].append(1)

    assert first.name == "first"
    assert second.name == "second"
    assert second.settings == {"values": []}
    assert first._asset_definition is definition
    assert second._asset_definition is definition


def test_definition_supports_multiple_resources_with_one_primary_usd():
    definition = AssetDefinition(
        registry_name="compound_embodiment",
        factory=_DummyAsset,
        tags=("embodiment",),
        asset_kind=AssetKind.EMBODIMENT,
        usd_resources={"robot": "/robot.usd", "stand": "/stand.usd"},
        primary_usd_name="robot",
    )

    assert definition.resolve_usd_path() == "/robot.usd"
    assert definition.usd_resources["stand"] == "/stand.usd"


def test_registry_stores_definitions_and_preserves_legacy_factory(monkeypatch):
    registry = _isolated_asset_registry(monkeypatch)
    registry.register(_DummyAsset)

    definition = registry.get_asset_definition("dummy")
    assert registry.get_asset_by_name("dummy") is _DummyAsset
    assert registry.get_asset_definitions_by_tag("object") == [definition]
    assert registry.get_assets_by_tag("object") == [_DummyAsset]

    asset = registry.create_asset("dummy", name="instance")
    assert isinstance(asset, _DummyAsset)
    assert asset.name == "instance"
    assert asset._asset_definition is definition


def test_registry_accepts_native_definition(monkeypatch):
    registry = _isolated_asset_registry(monkeypatch)
    definition = AssetDefinition(
        registry_name="native_dummy",
        factory=_DummyAsset,
        tags=("object", "native"),
        asset_kind=AssetKind.OBJECT,
        object_type=ObjectType.RIGID,
        default_params={"name": "from_definition"},
    )

    registry.register(definition)

    assert registry.get_asset_definition("native_dummy") is definition
    asset = registry.create_asset("native_dummy")
    assert asset.name == "from_definition"
    assert asset.registry_name == "native_dummy"

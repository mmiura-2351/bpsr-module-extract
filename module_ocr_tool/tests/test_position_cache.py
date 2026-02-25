from __future__ import annotations

from module_ocr_tool.app.position_cache import PositionCacheStore


def test_position_cache_update_lookup_and_reload(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    store = PositionCacheStore(config_path=config_path)
    store.load()

    key = "exc攻撃型モジュール精選|1920x1080"
    effect_regions = [
        {"left": 100, "top": 540, "width": 180, "height": 34},
        {"left": 100, "top": 627, "width": 180, "height": 34},
        {"left": 100, "top": 715, "width": 180, "height": 34},
    ]
    category_region = {"left": 650, "top": 205, "width": 150, "height": 30}

    store.update_success(
        module_name_key=key,
        module_name_raw="EXC攻撃型モジュール・精選",
        effect_regions=effect_regions,
        category_region=category_region,
    )
    looked_up = store.lookup(key)
    assert looked_up is not None
    assert looked_up.module_name_key == key
    assert looked_up.module_name_raw == "EXC攻撃型モジュール・精選"
    assert looked_up.effect_regions == effect_regions
    assert looked_up.category_region == category_region
    assert looked_up.success_count == 1
    assert looked_up.hit_count == 1

    reloaded = PositionCacheStore(config_path=config_path)
    reloaded.load()
    looked_up_reload = reloaded.lookup(key)
    assert looked_up_reload is not None
    assert looked_up_reload.effect_regions == effect_regions
    assert looked_up_reload.category_region == category_region
    assert looked_up_reload.success_count == 1
    assert looked_up_reload.hit_count == 2


def test_position_cache_mark_failure(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    store = PositionCacheStore(config_path=config_path)
    key = "卓越防御型モジュール|1920x1080"
    store.update_success(
        module_name_key=key,
        module_name_raw="卓越防御型モジュール",
        effect_regions=[{"left": 1, "top": 2, "width": 3, "height": 4}, None, None],
        category_region=None,
    )
    store.mark_failure(key)
    looked_up = store.lookup(key)
    assert looked_up is not None
    assert looked_up.failure_count == 1

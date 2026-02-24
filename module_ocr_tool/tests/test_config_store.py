from __future__ import annotations

from module_ocr_tool.app.config_store import AppConfig, load_app_config, save_app_config


def test_load_config_defaults_when_file_missing(tmp_path) -> None:
    config, path = load_app_config(str(tmp_path / "missing.json"))
    assert path.name == "missing.json"
    assert config.effect_regions == [None, None, None]
    assert config.last_export_path is None
    assert config.last_update_json_path is None


def test_save_and_load_config_roundtrip(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config = AppConfig(
        effect_regions=[
            {"left": 100, "top": 200, "width": 300, "height": 40},
            None,
            {"left": 100, "top": 280, "width": 300, "height": 40},
        ],
        last_export_path="C:/tmp/output.json",
        last_update_json_path="C:/tmp/existing.json",
    )
    save_app_config(config, config_path)

    loaded, loaded_path = load_app_config(str(config_path))
    assert loaded_path == config_path
    assert loaded.effect_regions[0] == {"left": 100, "top": 200, "width": 300, "height": 40}
    assert loaded.effect_regions[1] is None
    assert loaded.effect_regions[2] == {"left": 100, "top": 280, "width": 300, "height": 40}
    assert loaded.last_export_path == "C:/tmp/output.json"
    assert loaded.last_update_json_path == "C:/tmp/existing.json"


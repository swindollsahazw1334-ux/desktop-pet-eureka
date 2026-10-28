import json

import character


def test_persona_fills_names():
    text = character.persona("小明")
    assert "{me}" not in text and "{user}" not in text
    assert "小明" in text


def test_expression_map_falls_back_to_internal(monkeypatch):
    # character.json 里用中文名对应模型的表情名
    monkeypatch.setattr(character, "current", {**character.current, "expression_map": {"得意": "Smile"}})
    assert character.model_expression("3clever") == "Smile"
    assert character.model_expression("4OAO") == "4OAO"


def test_model_path_finds_first_model(tmp_path, monkeypatch):
    folder = tmp_path / "live2d_resources" / "Demo"
    folder.mkdir(parents=True)
    (folder / "Demo.model3.json").write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setattr(character, "get_app_path", lambda: str(tmp_path))
    monkeypatch.setattr(character, "current", {**character.current, "live2d_model": ""})
    assert character.model_path().endswith("Demo.model3.json")

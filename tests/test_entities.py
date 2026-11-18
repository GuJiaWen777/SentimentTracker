import json

from earlydata_weekly_publisher.entities import canonical_entity, normalize_entities


def test_company_aliases_collapse_to_one_canonical_name():
    assert canonical_entity("Pfizer", "company") == "辉瑞"
    assert canonical_entity("辉瑞制药", "company") == "辉瑞"
    assert canonical_entity("Bristol-Myers Squibb", "company") == "百时美施贵宝"
    assert normalize_entities(["Pfizer", "辉瑞", "辉瑞制药", "  "], "company") == ["辉瑞"]


def test_technology_aliases_collapse_spelling_variants():
    assert canonical_entity("CAR T", "technology") == "CAR-T"
    assert canonical_entity("抗体偶联药物", "technology") == "ADC"
    assert canonical_entity("GLP-1 受体激动剂", "technology") == "GLP-1"
    assert normalize_entities(["CAR-T", "CAR T", "ADC"], "technology") == ["CAR-T", "ADC"]


def test_custom_aliases_extend_and_override_the_builtin_dictionary(tmp_path, monkeypatch):
    path = tmp_path / "entities.json"
    path.write_text(
        json.dumps(
            {
                "company": {"默克": "默沙东", "辉瑞": "Pfizer"},
                "technology": {"类器官": "类器官模型"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EARLYDATA_ENTITY_ALIASES", str(path))

    assert canonical_entity("默克", "company") == "默沙东"
    assert canonical_entity("辉瑞", "company") == "Pfizer"
    assert canonical_entity("类器官", "technology") == "类器官模型"


def test_invalid_alias_files_do_not_break_normalization(tmp_path, monkeypatch):
    path = tmp_path / "entities.json"
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("EARLYDATA_ENTITY_ALIASES", str(path))

    assert canonical_entity("Pfizer", "company") == "辉瑞"
    assert canonical_entity("未知实体", "company") == "未知实体"

from __future__ import annotations
import pytest
from qcviz_mcp.llm.normalizer import analyze_follow_up_request, analyze_structure_input, extract_structure_candidate, normalize_user_text
from qcviz_mcp.services import ko_aliases
from qcviz_mcp.web.routes import compute as compute_route
pytestmark = [pytest.mark.contract]

def test_fallback_extract_structure_query_handles_korean_aliases():
    assert compute_route._fallback_extract_structure_query("벤젠의 HOMO 보여줘") == "benzene"
    assert compute_route._fallback_extract_structure_query("아세톤 ESP 맵 보여줘") == "acetone"
    assert compute_route._fallback_extract_structure_query("물의 전하 계산해줘") == "water"
    assert compute_route._fallback_extract_structure_query("메틸아민 계산해줘") == "methylamine"
    assert compute_route._fallback_extract_structure_query("TFSI- EMIM +이온쌍에 대한 계산 ㄱㄱ") == "TFSI- EMIM +"


def test_prepare_payload_heuristic_extracts_orbital_method_basis(monkeypatch):
    monkeypatch.setattr(compute_route, "get_qcviz_agent", lambda: None, raising=False)
    payload = {"message": "Show HOMO of benzene with B3LYP and def2-SVP"}
    prepared = compute_route._prepare_payload(payload)
    assert prepared["job_type"] == "orbital_preview"
    assert prepared["structure_query"].lower() == "benzene"
    assert prepared["method"].lower() == "b3lyp"
    assert prepared["basis"].lower() == "def2-svp"
    assert prepared["planner_applied"] is True

def test_prepare_payload_extracts_xyz_block(monkeypatch):
    monkeypatch.setattr(compute_route, "get_qcviz_agent", lambda: None, raising=False)
    payload = {"job_type": "single_point", "message": """Compute energy for this structure:
```xyz
3
water
O  0.000000  0.000000  0.000000
H  0.000000  0.757160  0.586260
H  0.000000 -0.757160  0.586260
```"""}
    prepared = compute_route._prepare_payload(payload)
    assert prepared["job_type"] == "single_point"
    assert "O  0.000000  0.000000  0.000000" in prepared["xyz"]

def test_prepare_payload_esp_message_extracts_preset(monkeypatch):
    monkeypatch.setattr(compute_route, "get_qcviz_agent", lambda: None, raising=False)
    payload = {"message": "Render ESP map for acetone using ACS preset"}
    prepared = compute_route._prepare_payload(payload)
    assert prepared["job_type"] == "esp_map"
    assert prepared["structure_query"].lower() == "acetone"
    assert prepared["esp_preset"] == "acs"


def test_normalize_user_text_does_not_treat_esp_preset_as_unknown_acronym():
    normalized = normalize_user_text("Render ESP map for acetone using ACS preset")
    assert normalized["query_kind"] == "compute_ready"
    assert normalized["semantic_grounding_needed"] is False
    assert normalized["unknown_acronyms"] == []
    assert normalized["maybe_structure_hint"].lower() == "acetone"


def test_normalize_user_text_does_not_route_basis_followup_to_semantic_grounding():
    normalized = normalize_user_text("basis만 더 키워봐")
    assert normalized["follow_up_mode"] == "modify_parameters"
    assert normalized["query_kind"] == "compute_ready"
    assert normalized["semantic_grounding_needed"] is False

def test_prepare_payload_without_structure_raises(monkeypatch):
    monkeypatch.setattr(compute_route, "get_qcviz_agent", lambda: None, raising=False)
    with pytest.raises(Exception) as exc:
        compute_route._prepare_payload({"message": "HOMO 보여줘"})
    assert "Structure not recognized" in str(exc.value)


def test_extract_structure_candidate_recognizes_bare_english_molecule_name():
    assert extract_structure_candidate("Biphenyl") == "Biphenyl"
    assert extract_structure_candidate("biphenyl HOMO") == "biphenyl"
    assert extract_structure_candidate("benzoic acid HOMO") == "benzoic acid"
    assert extract_structure_candidate("2,4,6-TRINITROTOLUENE") == "2,4,6-TRINITROTOLUENE"
    assert extract_structure_candidate("2,4,6-TRINITROTOLUENE HOMO") == "2,4,6-TRINITROTOLUENE"
    assert extract_structure_candidate("메틸아민") == "methylamine"
    assert extract_structure_candidate("CH₃NH₂ /") == "CH3NH2"
    assert extract_structure_candidate("뷰타 다이엔 구조만 보여줘") in {"butadiene", "1,3-butadiene"}


def test_analyze_structure_input_decomposes_formula_alias_mixed_input():
    analysis = analyze_structure_input("CH3COOH (acetic acid)")
    assert analysis["formula_mentions"] == ["CH3COOH"]
    assert analysis["alias_mentions"] == ["acetic acid"]
    assert analysis["canonical_candidates"] == ["acetic acid", "ethanoic acid", "CH3COOH"]


def test_analyze_structure_input_handles_reverse_formula_alias_order():
    analysis = analyze_structure_input("acetic acid (CH3COOH)")
    assert analysis["formula_mentions"] == ["CH3COOH"]
    assert analysis["alias_mentions"] == ["acetic acid"]
    assert analysis["canonical_candidates"] == ["acetic acid", "ethanoic acid", "CH3COOH"]


def test_analyze_structure_input_handles_subscript_formula_alias_mixed_input():
    analysis = analyze_structure_input("CH₃NH₂ (methylamine)")
    assert analysis["formula_mentions"] == ["CH3NH2"]
    assert analysis["alias_mentions"] == ["methylamine"]
    assert analysis["canonical_candidates"] == ["methylamine", "methanamine", "CH3NH2"]


def test_analyze_structure_input_handles_water_formula_alias_mixed_input():
    analysis = analyze_structure_input("H2O (water)")
    assert analysis["formula_mentions"] == ["H2O"]
    assert analysis["alias_mentions"] == ["water"]
    assert analysis["canonical_candidates"] == ["water", "H2O"]


def test_prepare_payload_canonicalizes_formula_alias_mixed_input(monkeypatch):
    monkeypatch.setattr(compute_route, "get_qcviz_agent", lambda: None, raising=False)
    prepared = compute_route._prepare_payload({"message": "CH3COOH (acetic acid)"})
    assert prepared["structure_query"] == "acetic acid"
    assert prepared["structure_query_candidates"] == ["acetic acid", "ethanoic acid", "CH3COOH"]
    assert prepared["formula_mentions"] == ["CH3COOH"]
    assert prepared["alias_mentions"] == ["acetic acid"]


def test_normalize_user_text_detects_ion_pair_components():
    normalized = normalize_user_text("EMIM TFSI")
    assert normalized["composition_kind"] == "ion_pair"
    assert normalized["structures"] == [
        {"name": "EMIM", "charge": 1},
        {"name": "TFSI", "charge": -1},
    ]


def test_normalize_user_text_detects_salt_components():
    normalized = normalize_user_text("LiTFSI")
    assert normalized["composition_kind"] == "salt"
    assert normalized["structures"] == [
        {"name": "LI", "charge": 1},
        {"name": "TFSI", "charge": -1},
    ]


def test_normalize_user_text_preserves_charge_hint_for_explicit_anion():
    normalized = normalize_user_text("TFSI-")
    assert normalized["charge_hint"] == -1
    assert normalized["structures"] == [{"name": "TFSI", "charge": -1}]


@pytest.mark.parametrize(
    ("message", "expected_mode", "expected_job_type", "expected_orbital"),
    [
        ("ESP도", "add_analysis", "esp_map", None),
        ("ESP ㄱㄱ", "add_analysis", "esp_map", None),
        ("LUMO도", "add_analysis", "orbital_preview", "LUMO"),
        ("basis만 더 키워봐", "modify_parameters", None, None),
        ("이걸 최적화해줘", "optimize_same_structure", "geometry_optimization", None),
    ],
)
def test_analyze_follow_up_request_classifies_common_elliptical_followups(
    message, expected_mode, expected_job_type, expected_orbital
):
    follow_up = analyze_follow_up_request(message)
    assert follow_up["follow_up_mode"] == expected_mode
    assert follow_up["job_type"] == expected_job_type
    assert follow_up["orbital"] == expected_orbital


def test_analysis_only_followup_does_not_pollute_structure_candidates():
    message = "HOMO LUMO ESP가 궁금"
    normalized = normalize_user_text(message)
    follow_up = analyze_follow_up_request(message)
    assert "궁금" not in [str(item).strip() for item in (normalized.get("canonical_candidates") or [])]
    assert not normalized.get("maybe_structure_hint")
    assert set(normalized.get("analysis_bundle") or []) >= {"HOMO", "LUMO", "ESP"}
    assert follow_up["follow_up_mode"] == "add_analysis"
    assert follow_up["requires_context"] is True


def test_korean_pronoun_followup_does_not_become_structure_candidate():
    message = "ㅇㅇ 그거 HOMO LUMO ESP"
    normalized = normalize_user_text(message)
    follow_up = analyze_follow_up_request(message)
    assert extract_structure_candidate(message) is None
    assert normalized.get("maybe_structure_hint") in {None, ""}
    assert set(normalized.get("analysis_bundle") or []) >= {"HOMO", "LUMO", "ESP"}
    assert follow_up["follow_up_mode"] == "add_analysis"
    assert follow_up["requires_context"] is True
    assert normalized["semantic_grounding_needed"] is False


def test_korean_pronoun_optimize_followup_stays_in_same_structure_lane():
    follow_up = analyze_follow_up_request("그걸 최적화해줘")
    assert follow_up["follow_up_mode"] == "optimize_same_structure"
    assert follow_up["job_type"] == "geometry_optimization"
    assert follow_up["requires_context"] is True


def test_semantic_descriptor_does_not_promote_raw_phrase_to_structure_candidate():
    message = "TNT에 들어가는 주물질"
    normalized = normalize_user_text(message)
    assert normalized["semantic_descriptor"] is True
    assert normalized["maybe_structure_hint"] in {None, ""}
    option_values = [str(item).strip() for item in (normalized.get("candidate_queries") or [])]
    assert message not in option_values
    assert "TNT 에 들어가는 주물질" not in option_values


def test_korean_alias_translation_does_not_match_inside_generic_descriptor_words():
    assert ko_aliases.translate("주물질") == "주물질"
    assert ko_aliases.find_molecule_name("주물질") is None
    assert ko_aliases.translate("TNT에 들어가는 주물질") == "TNT에 들어가는 주물질"


def test_short_followup_esp_go_go_does_not_become_structure_candidate():
    message = "ESP ㄱㄱ"
    normalized = normalize_user_text(message)
    follow_up = analyze_follow_up_request(message)
    assert not normalized.get("canonical_candidates")
    assert not normalized.get("maybe_structure_hint")
    assert set(normalized.get("analysis_bundle") or []) >= {"ESP"}
    assert follow_up["follow_up_mode"] == "add_analysis"
    assert follow_up["requires_context"] is True


def test_prepare_payload_detects_emim_tfsi_as_structured_ion_pair(monkeypatch):
    monkeypatch.setattr(compute_route, "get_qcviz_agent", lambda: None, raising=False)
    prepared = compute_route._prepare_payload({"message": "EMIM TFSI 에너지"})
    assert prepared["structures"] == [
        {"name": "EMIM", "charge": 1},
        {"name": "TFSI", "charge": -1},
    ]
    assert prepared["composition_kind"] == "ion_pair"


def test_prepare_payload_detects_litfsi_as_structured_salt(monkeypatch):
    monkeypatch.setattr(compute_route, "get_qcviz_agent", lambda: None, raising=False)
    prepared = compute_route._prepare_payload({"message": "LiTFSI 에너지"})
    assert prepared["structures"] == [
        {"name": "LI", "charge": 1},
        {"name": "TFSI", "charge": -1},
    ]
    assert prepared["composition_kind"] == "salt"


def test_normalize_user_text_detects_multi_molecule_batch_request():
    paragraph = """
    (a) 아민 CH3NH2 (methylamine) – 탄소에 -NH2 작용기가 결합한 가장 간단한 1차 아민입니다.
    (b) 카복실산 CH3COOH (acetic acid) – 메틸기에 -COOH 작용기가 결합했습니다.
    (c) 이중결합 2개 CH2=CH-CH=CH2 (1,3-뷰타다이엔) – C=C 이중결합 2개가 있는 구조입니다.
    (d) 카보닐 CH3CHO (acetaldehyde) – 카보닐기를 포함한 알데하이드입니다.
    여기에 나오는 물질들 싹다 구조구하고 homo lumo esp다 구해
    """
    normalized = normalize_user_text(paragraph)
    assert normalized["target_scope"] == "all_mentioned"
    assert normalized["selection_mode"] == "explicit_all"
    assert normalized["batch_request"] is True
    assert len(normalized["selected_molecules"]) == 4
    assert set(normalized["analysis_bundle"]) == {"structure", "HOMO", "LUMO", "ESP"}


def test_normalize_user_text_treats_next_lumo_as_follow_up_without_structure_candidate():
    normalized = normalize_user_text("\uc774\ubc88\uc5d4 LUMO")
    assert extract_structure_candidate("\uc774\ubc88\uc5d4 LUMO") is None
    assert normalized["follow_up_mode"] == "add_analysis"
    assert normalized["follow_up_orbital"] == "LUMO"
    assert normalized["follow_up_requires_context"] is True
    assert normalized.get("maybe_structure_hint") in {None, ""}


def test_normalize_user_text_treats_direct_english_optimize_prompts_as_explicit_structure_compute():
    glycine = normalize_user_text("glycine optimize geometry")
    acetic = normalize_user_text("acetic acid optimize geometry")
    assert extract_structure_candidate("glycine optimize geometry") == "glycine"
    assert extract_structure_candidate("acetic acid optimize geometry") == "acetic acid"
    assert glycine["follow_up_mode"] is None
    assert acetic["follow_up_mode"] is None
    assert glycine["follow_up_requires_context"] is False
    assert acetic["follow_up_requires_context"] is False
    assert (glycine.get("maybe_structure_hint") or "").lower() == "glycine"
    assert (acetic.get("maybe_structure_hint") or "").lower() == "acetic acid"


def test_normalize_user_text_keeps_basis_concept_questions_in_chat_lane():
    normalized = normalize_user_text("What is a basis set?")
    follow_up = analyze_follow_up_request("What is a basis set?")
    assert follow_up["follow_up_mode"] is None
    assert follow_up["requires_context"] is False
    assert normalized["query_kind"] == "chat_only"
    assert normalized["chat_only"] is True
    assert normalized["semantic_grounding_needed"] is False


def test_analyze_follow_up_request_treats_optimize_it_too_as_same_structure_follow_up():
    normalized = normalize_user_text("Optimize it too")
    follow_up = analyze_follow_up_request("Optimize it too")
    assert extract_structure_candidate("Optimize it too") is None
    assert follow_up["follow_up_mode"] == "optimize_same_structure"
    assert follow_up["job_type"] == "geometry_optimization"
    assert follow_up["requires_context"] is True
    assert normalized["follow_up_mode"] == "optimize_same_structure"
    assert normalized["follow_up_requires_context"] is True
    assert normalized.get("maybe_structure_hint") in {None, ""}


def test_normalize_user_text_detects_korean_method_parameter_followup_with_particles():
    normalized = normalize_user_text("method를 PBE0로 바꿔")
    follow_up = analyze_follow_up_request("method를 PBE0로 바꿔")
    assert follow_up["follow_up_mode"] == "modify_parameters"
    assert (follow_up["method_hint"] or "").upper() == "PBE0"
    assert follow_up["requires_context"] is True
    assert normalized["follow_up_mode"] == "modify_parameters"
    assert (normalized.get("follow_up_method_hint") or "").upper() == "PBE0"
    assert normalized["follow_up_requires_context"] is True
    assert normalized["semantic_grounding_needed"] is False


def test_normalize_user_text_parameter_only_basis_followup_requires_context():
    normalized = normalize_user_text("basis\ub9cc \ub354 \ud0a4\uc6cc\ubd10")
    assert extract_structure_candidate("basis\ub9cc \ub354 \ud0a4\uc6cc\ubd10") is None
    assert normalized["follow_up_mode"] == "modify_parameters"
    assert normalized["follow_up_requires_context"] is True
    assert normalized["query_kind"] == "compute_ready"


def test_normalize_user_text_parameter_only_method_followup_requires_context():
    normalized = normalize_user_text("method\ub97c B3LYP\ub85c \ubc14\uafd4")
    assert extract_structure_candidate("method\ub97c B3LYP\ub85c \ubc14\uafd4") is None
    assert normalized["follow_up_mode"] == "modify_parameters"
    assert normalized["follow_up_method_hint"] == "B3LYP"
    assert normalized["follow_up_requires_context"] is True
    assert normalized["query_kind"] == "compute_ready"


def test_extract_structure_candidate_prefers_explicit_structure_for_optimize_geometry_request():
    normalized = normalize_user_text("water optimize geometry")
    assert extract_structure_candidate("water optimize geometry") == "water"
    assert normalized["query_kind"] == "compute_ready"
    assert normalized.get("follow_up_mode") in {None, ""}
    assert normalized["maybe_structure_hint"] == "water"


def test_extract_structure_candidate_preserves_full_locant_name_for_tnt():
    assert extract_structure_candidate("2,4,6-TRINITROTOLUENE") == "2,4,6-TRINITROTOLUENE"
    assert extract_structure_candidate("2,4,6-TRINITROTOLUENE HOMO 보여줘") == "2,4,6-TRINITROTOLUENE"


def test_normalize_user_text_preserves_full_locant_name_instead_of_falling_back_to_toluene():
    normalized = normalize_user_text("2,4,6-TRINITROTOLUENE HOMO 보여줘")
    assert normalized["maybe_structure_hint"] == "2,4,6-TRINITROTOLUENE"
    assert normalized["candidate_queries"][0] == "2,4,6-TRINITROTOLUENE"

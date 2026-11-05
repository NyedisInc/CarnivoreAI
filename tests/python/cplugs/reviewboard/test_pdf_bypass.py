
from __future__ import annotations

import pytest

from src.cplugs.reviewboard import pdf_scan
from src.cplugs.reviewboard.pdf_streams import PdfUnreadable
from src.cplugs.sdk.file_secrets import Deadline
from tests.python.cplugs.reviewboard.pdf_fixtures import BYPASSES, ORDINARY, ROUND9_REVIEW


READ_OK_EXCLUDED = {"objstm_predictor_plus_sign", "objstm_lzw", "duplicate_filter_key", "objstm_string_moves_cut", "hidden_in_stream_body", "hidden_in_image_stream", "hidden_gen_six_digits", "hidden_vtab_separator", "hidden_comment_before_obj", "hidden_comment_between_numbers",
                    "hidden_objstm_in_stream_body", "hidden_xref_and_catalog", "three_d_on_instantiate", "dup_action_type_gotor_first", "dup_s_in_action",
                    "hidden_sliding_one_number", "hidden_sliding_three_numbers", "hidden_vtab_after_obj", "xref_stream_predictor_into_body", "xref_stream_flate_into_body", "xref_prev_chain_into_body", "xref_type2_hidden_objstm",
                    "hidden_gen_glued_obj", "hidden_plus_gen", "hidden_minus_gen", "hidden_plus_gen_glued_obj", "hidden_leadingzero_glued_obj", "hidden_obj_glued_to_dict", "hidden_mixed_ws_then_glued_obj", "hidden_leading_comment_at_offset"}

READ_OK_EXCLUDED |= set(ROUND9_REVIEW)


@pytest.mark.parametrize("name", sorted(BYPASSES))
def test_every_bypass_is_refused(name):
    try:
        found = pdf_scan.features(BYPASSES[name](), Deadline())
    except PdfUnreadable:
        return
    assert found, f"{name} passed as clean"


@pytest.mark.parametrize("name", sorted(n for n in BYPASSES if n not in READ_OK_EXCLUDED))
def test_the_bypasses_that_can_be_read_are_read_not_just_refused(name):
    assert pdf_scan.features(BYPASSES[name](), Deadline()) == {"JavaScript"}


@pytest.mark.parametrize("name", sorted(ORDINARY))
def test_ordinary_files_stay_clean(name):
    assert pdf_scan.features(ORDINARY[name](), Deadline()) == frozenset()


@pytest.mark.parametrize("name,reason", [
    ("hidden_in_stream_body", "hidden_object"), ("hidden_in_image_stream", "hidden_object"), ("hidden_objstm_in_stream_body", "hidden_object"),
    ("hidden_xref_and_catalog", "hidden_object"), ("hidden_gen_six_digits", "hidden_object"), ("hidden_vtab_separator", "hidden_object"), ("hidden_comment_before_obj", "hidden_object"),
    ("hidden_comment_between_numbers", "hidden_object"), ("objstm_string_moves_cut", "hidden_object"),
    ("hidden_sliding_one_number", "hidden_object"), ("hidden_sliding_three_numbers", "hidden_object"), ("hidden_vtab_after_obj", "hidden_object"),
    ("xref_stream_predictor_into_body", "hidden_object"), ("xref_stream_flate_into_body", "hidden_object"), ("xref_prev_chain_into_body", "hidden_object"),
    ("xref_type2_hidden_objstm", "hidden_object"),
    ("hidden_gen_glued_obj", "hidden_object"), ("hidden_plus_gen", "hidden_object"), ("hidden_minus_gen", "hidden_object"), ("hidden_plus_gen_glued_obj", "hidden_object"),
    ("hidden_leadingzero_glued_obj", "hidden_object"), ("hidden_obj_glued_to_dict", "hidden_object"), ("hidden_mixed_ws_then_glued_obj", "hidden_object"),
    ("hidden_leading_comment_at_offset", "hidden_object"),
    *[(n, "malformed_pdf" if "60" in n else "hidden_object") for n in ROUND9_REVIEW],
    ("dup_action_type_gotor_first", "ambiguous_object"), ("dup_s_in_action", "ambiguous_object"),
])
def test_hidden_and_doubled_objects_are_refused_for_their_own_reason(name, reason):
    with pytest.raises(PdfUnreadable) as exc:
        pdf_scan.features(BYPASSES[name](), Deadline())
    assert exc.value.reason == reason


def test_a_3d_annotation_script_is_found_without_any_js_name():
    assert pdf_scan.features(BYPASSES["three_d_on_instantiate"](), Deadline()) == {"3DScript"}

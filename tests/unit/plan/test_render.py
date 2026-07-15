from loop_sci.plan.render import PLAN_FIELD_TITLES, assert_json_markdown_parity, render_markdown
from tests.unit.plan.test_schemas import _plan  # reuse the builder


def test_markdown_contains_all_12_field_titles():
    md = render_markdown(_plan())
    for title in PLAN_FIELD_TITLES.values():
        assert f"## {title}" in md


def test_parity_holds_for_complete_plan():
    assert_json_markdown_parity(_plan())  # must not raise

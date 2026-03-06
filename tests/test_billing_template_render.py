from __future__ import annotations

from core.billing.template_render import list_placeholders, render_template


def test_render_template_replaces_known_placeholders_and_leaves_unknown():
    tpl = "Hi {{name}}. Total {{total}}. Unknown {{nope}}."
    out = render_template(tpl, {"name": "Adam", "total": "10"})
    assert out == "Hi Adam. Total 10. Unknown {{nope}}."


def test_list_placeholders_unique_in_order():
    tpl = "{{a}} {{b}} {{a}} {{c}}"
    assert list_placeholders(tpl) == ["a", "b", "c"]


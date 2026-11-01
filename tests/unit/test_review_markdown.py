import pytest

from app.services.review_markdown import code, markdown


def test_formats_symbols_without_double_wrapping_explicit_code():
    assert markdown("Pass tenant_id to `find_customer()` in customers.py.") == (
        "Pass `tenant_id` to `find_customer()` in `customers.py`."
    )


def test_preserves_code_operators_and_language_fences():
    text = "Use `a < b`:\n\n```python\nif a < b:\n    return user_id\n```"
    assert markdown(text) == text


@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_closes_only_valid_fences_and_keeps_html_inside_code(fence):
    text = f"{fence}html\n</details>\n{fence} trailing\n{fence}"
    result = markdown(text)
    assert result.startswith("```html\n") or result.startswith("````html\n")
    assert "</details>" in result and f"{fence} trailing" in result


@pytest.mark.parametrize(
    "text", ["```python\nreturn 0", "~~~python\nreturn 0", "`unclosed"]
)
def test_unclosed_code_cannot_swallow_host_evidence(text):
    result = markdown(text)
    assert not result.startswith(("```", "~~~", "`unclosed"))


def test_neutralizes_prose_html_mentions_images_and_control_markers():
    result = markdown(
        "</details> @someone ![pixel](https://evil.test)\n`<!-- rush:resolved -->`"
    )
    assert "&lt;/details>" in result and "@\u200bsomeone" in result
    assert "!\\[pixel]" in result
    assert "<!-- rush:resolved -->" not in result


def test_longer_code_delimiters_protect_embedded_backticks():
    assert code("`value`") == "`` `value` ``"
    assert markdown("~~~text\n```\n~~~") == "````text\n```\n````"


def test_suggestion_fences_are_readable_examples_not_applyable_patches():
    assert markdown("```suggestion\nreturn 0\n```") == "```text\nreturn 0\n```"


def test_preserves_unicode_line_separator_inside_a_code_string():
    text = '```javascript\nconst value = "a\u2028b";\n```'
    assert markdown(text) == text


@pytest.mark.parametrize(
    "text",
    [
        r"Use \`<details><summary>hide evidence</summary>`",
        r"\func(<details><summary>hide</summary>)",
        r"\\\func(<img src='https://evil.test'>)",
    ],
)
def test_prose_backslashes_cannot_disable_generated_code_protection(text):
    from markdown_it import MarkdownIt

    rendered = MarkdownIt().render(markdown(text))
    assert "<details>" not in rendered and "<img " not in rendered
    assert "&lt;" in rendered

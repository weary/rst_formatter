from difflib import unified_diff

import pytest  # noqa: F401

from rst_formatter import RstFormatterConfig, fix_multiline_headings, format_rst


def print_unified_diff(left: str, right: str) -> None:
    diff = list(unified_diff(left.splitlines(), right.splitlines(), lineterm=""))
    print("\n".join(diff))


def test_simple_text():
    input_text = """Hello, dear world. How are you?"""
    actual_text = format_rst(input_text)
    print_unified_diff(actual_text, input_text)
    assert actual_text == input_text


def test_fix_multiline_heading():
    input_text = """
---
My Title
----
some text.
""".strip()

    expected_output = """
----
My Title
----
some text.
""".strip()

    for testchar in ("-", "=", "^"):
        inp = input_text.replace("-", testchar)
        exp = expected_output.replace("-", testchar)
        act = fix_multiline_headings(inp, config=RstFormatterConfig())
        assert exp == act


def test_rst_multiline_title():
    config = RstFormatterConfig()
    input_text = """
---
My Title
----
some text.
""".strip()

    expected_output1 = """
========
My Title
========

some text.
""".strip()

    actual_output1 = format_rst(input_text, config=config)
    if actual_output1 != expected_output1:
        print("XXX test 1:")
        print("actual:\n" + actual_output1)
        print("\n\nexpected:" + expected_output1)
    assert actual_output1 == expected_output1

    config.newline_after_title = -1

    expected_output2 = """
========
My Title
========
some text.
""".strip()

    actual_output2 = format_rst(input_text, config=config)
    assert actual_output2 == expected_output2


def test_simple_bullet_list():
    config = RstFormatterConfig()
    input_text = """
Some text:
- line 1
- line 2

More text
""".strip()

    expected_output1 = input_text

    actual_output1 = format_rst(input_text, config=config)
    assert actual_output1 == expected_output1


def test_extra_bullet_list():
    config = RstFormatterConfig()
    config.title_order = ["-"]
    input_text = """
Heading
-------
- bullet 1
- bullet 2
  second line of bullet 2,
  which is rather long.

  third line of bullet 2
- bullet 3

  - sublist item 1
  - sublist item 2
- bullet 4

regular text
""".strip()

    expected_output1 = """
Heading
-------

- bullet 1
- bullet 2 second line of bullet 2, which is rather long.

  third line of bullet 2
- bullet 3

  - sublist item 1
  - sublist item 2
- bullet 4

regular text
""".strip()

    actual_output1 = format_rst(input_text, config=config)
    print_unified_diff(actual_output1, expected_output1)
    assert actual_output1 == expected_output1


def test_inline_markup():
    input_text = """
**Bold** *Italic* `some official ref`_ and another `official ref`_.

_`some official ref` is here, _`official ref` as well.
    """.strip()
    actual_text = format_rst(input_text)
    print_unified_diff(actual_text, input_text)
    assert actual_text == input_text


def test_directives():
    input_text = """

.. some_directive_with_content::

  macro content
.. directive_with_args_on_line:: some_arg other_arg
.. directive_with_named_args::
  :arg: frut

.. directive_with_named_args_and_content::
  :arg: frut

  content
no content
    """.strip()
    actual_text = format_rst(input_text)
    print("actual:\n" + actual_text + "\n")
    print_unified_diff(actual_text, input_text)
    assert actual_text == input_text
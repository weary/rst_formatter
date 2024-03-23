"""Testcases for rst_formatter."""

import argparse
import re
import tempfile
from difflib import unified_diff

import pytest  # noqa: F401
from rst_formatter import RstFormatterConfig, fix_heading_line_length, format_rst, main


def print_unified_diff(left: str, right: str) -> None:
    """Test-function that prints output similar to 'diff -u'."""
    diff = list(unified_diff(left.splitlines(), right.splitlines(), lineterm=""))
    print("\n".join(diff))


def print_with_line_numbers(name: str, content: str) -> None:
    """Test-function that prints a block of code with line numbers prepended."""
    print(f"content of {name}:")
    for idx, line in enumerate(content.split("\n")):
        print(f"{idx+1:3}: '{line}'")
    print()


def test_simple_text() -> None:
    """Basic testcase."""
    input_text = """Hello, dear world. How are you?"""
    actual_text = format_rst(input_text)
    print_unified_diff(actual_text, input_text)
    assert actual_text == input_text


def test_fix_multiline_heading() -> None:
    """Test the regular expression that will fix the title line length to 4."""
    input_text = """
---
My Title
-----
some text.
""".strip()

    expected_output = """
----
My Title
----
some text.
""".strip()

    for test_char in ("-", "=", "^"):
        inp = input_text.replace("-", test_char)
        exp = expected_output.replace("-", test_char)
        act = fix_heading_line_length(inp, config=RstFormatterConfig())
        assert exp == act


def test_consecutive_headings() -> None:
    """Test headings one-after-another."""
    input_text = """
====
Heading1
====
Heading2
====
Heading3
----
Heading4
^^^^
"""
    expected_output = """
========
Heading1
========

Heading2
========

Heading3
--------
Heading4
^^^^^^^^
""".strip()
    actual_output = format_rst(input_text)
    assert actual_output == expected_output


def test_rst_multiline_title() -> None:
    """Test above-and-below titles are correctly replaced according to the config."""
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


def test_simple_bullet_list() -> None:
    """Test a basic bullet list."""
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


def test_extra_bullet_list() -> None:
    """Test many sidecases with newlines and bullet lists."""
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
    assert actual_output1 == expected_output1


def test_inline_markup() -> None:
    """Check the formatting of special nodes is preserved."""
    input_text = """
**Bold** *Italic* `some official ref`_ and another `official ref`_ and a ~custom regex~.

_`some official ref` is here, _`official ref` as well.
    """.strip()
    actual_text = format_rst(input_text)
    assert actual_text == input_text


def test_directives() -> None:
    """Test many forms of directives."""
    input_text = """

.. some_directive_with_content::
  macro content

.. directive_with_args_on_line:: some_arg other_arg

.. directive_with_named_args_and_no_content::
  :arg: frut

.. directive_with_named_args_and_content::
  :arg: frut

  content

no content

Known directive:

.. csv-table:: tablename
  :header: "header 1", "header 2"
  :widths: 30, 100

  col1, col2

Bla

.. somedirective_without_arguments_and_no_blank_line::
  line 1
  line 2

Remainder
    """.strip()
    actual_text = format_rst(input_text)
    assert actual_text == input_text


def test_directives_short() -> None:
    """Test the most short syntax for a directive."""
    input_text = """
Bla
.. directive_without_leading_newline::
Remainder
    """.strip()

    expected_text = """
Bla

.. directive_without_leading_newline::

Remainder
    """.strip()

    actual_text = format_rst(input_text)
    assert actual_text == expected_text


def test_reference() -> None:
    """Test many different reference formats."""
    input_text = """
Chapter 1
=========

My *favorite* language is Python_.

.. _Python: https://www.python.org/

Continue reading in `Somewhere <Chapter 4>`_.

`Chapter 1`_ describes something

L1: `Something Else <something.other>`_ is outside this document.

L2: `something.other`_ is outside this document.

Lorem ipsum [Ref]_ dolor sit amet.

.. [Ref] Book or article reference, URL or whatever.

Chapter 4
=========

Bla
""".strip()

    config = RstFormatterConfig(title_order=["="])
    actual_text = format_rst(input_text, config)
    assert actual_text == input_text


def test_line_wrap() -> None:
    """Test the lines are not wrapped, but not inside unbreakable nodes."""
    unbreakable = "~a b c d e~"
    input_text = unbreakable * 2
    actual_text = format_rst(input_text)
    expected_text = f"{unbreakable} {unbreakable}"
    print_with_line_numbers("input", input_text)
    print_with_line_numbers("actual", actual_text)
    assert actual_text == expected_text

    config = RstFormatterConfig(max_line_length=40)
    input_text = unbreakable * 50
    actual_text = format_rst(input_text, config)
    lines = actual_text.split("\n")
    assert all(len(line) < config.max_line_length for line in lines)
    assert all(len(line) > config.max_line_length - len(unbreakable) for line in lines[:-1])


def test_config_argparse() -> None:
    """Test if all argparse options can be set."""
    parser = argparse.ArgumentParser()
    RstFormatterConfig.prepare_argparse(parser)
    args = parser.parse_args(
        """
--max_line_length=10
--no_line_break [a-z]+ b+
--titles # ^
--newline_after_title 3
--newline_bullet_list
--print-parse-tree
""".split()
    )
    expected = RstFormatterConfig(
        max_line_length=10,
        no_line_break_regexes=[re.compile("[a-z]+"), re.compile("b+")],
        title_order=["#", "^"],
        newline_after_title=3,
        newline_bullet_list=True,
        print_node_tree=True,
    )
    config = RstFormatterConfig.parse_argparse(args)
    assert config == expected


def test_main() -> None:
    """Test if the main loop can be run."""
    rst_file = tempfile.NamedTemporaryFile()
    rst_file.write(b"something  or  other")
    rst_file.flush()

    assert main([rst_file.name, "--silent", "--diff", "--print-parse-tree"]) != 0
    assert main([rst_file.name, "--diff"]) != 0
    assert main([rst_file.name]) != 0
    assert main([rst_file.name]) == 0
    rst_file.seek(0)
    out = rst_file.read()
    assert out == b"something or other"

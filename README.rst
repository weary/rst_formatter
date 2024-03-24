=============
rst_formatter
=============

Tool to format the an '.rst' (restructured-text) document.

The tool will:
- Re-flow paragraphs, so they fill up to the maximum line length and remove
  line-breaks that are not a paragraph-break.
- Fix heading formatting, both length-of-headers, and used heading-type.
- Remove redundant and insert missing blank lines.

The tool will parse the input document using docutils and write out an.rst
document using a docutils writer. This means the resulting document is as close
as an '.rst' can get to the rendered content.

Optionally, if the document contains python directives, the python code can be
formatted using 'ruff'.
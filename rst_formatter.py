import re
import sys
from typing import Any

from docutils import io, nodes, writers
from docutils.core import publish_doctree, publish_from_doctree
from docutils.parsers.rst import Directive, Parser, directives
from docutils.parsers.rst.directives.misc import Raw
from docutils.parsers.rst.states import Body, Inliner, Line
from docutils.readers.standalone import Reader

test_document = """
====
section 7
====

Para 1
----

Subpara 2
&&&&

- bullet 1
- bullet 2
  second line of bullet 2, which is rather long.

  third line of bullet 2
- bullet 3

  - sublist item 1
  - sublist item 2
- bullet 4

My ref: ~my ref~
in a multiline paragraph.

**Bold** *Italic* `some official ref`_ and another `official ref`_.

_`some official ref` is here, _`official ref` as well.

.. some_macro::

"""


class ModelReferenceNode(nodes.General, nodes.Inline, nodes.Referential, nodes.TextElement):
    def __init__(self, ref: str) -> None:
        super().__init__()
        self.ref = ref

    def pformat(self, indent: str = "    ", level: int = 0):
        assert not self.children
        return f"{indent * level}~{self.ref}~\n"


class MyParser(Parser):
    """Custom rst parser that will also recognize ~references~."""

    def __init__(self) -> None:
        """Construct MyParser."""
        inliner = Inliner()

        def model_ref_node_factory(match: re.Match, _lineno: int) -> list[nodes.Node]:
            return [ModelReferenceNode(match.group(1))]

        inliner.implicit_dispatch.append((re.compile(r"~([^~]*)~"), model_ref_node_factory))

        super().__init__(rfc2822=False, inliner=inliner)


class RstTranslator(nodes.NodeVisitor):
    ignored_nodes = (nodes.document,)

    def __init__(self, document: nodes.document, max_line_length: int = 120) -> None:
        super().__init__(document)
        self.output = []  # the final output
        self.hold_space: list[list[str]] = []  # inside something non-breakable
        self.line_length = 0  # where is my cursor
        self.max_line_length = max_line_length  # when to insert a newline
        self.indent_level = 0
        self.indent = "  "
        self.section_depth = 0  # for the heading characters
        self.bullet_char: list[str] = []
        self.after_list_item: bool = False

    def _append_word_wrap(self, text: list[str]) -> None:
        for word in text:
            if not word:
                continue
            if self.line_length + 1 + len(word) > self.max_line_length:
                self.append(newlines=1)
            if self.line_length == 0:
                indent = self.indent * self.indent_level
                self.line_length += len(indent) + len(word)
                self.output.extend([indent, word])
            else:
                self.line_length += 1 + len(word)
                self.output.extend([" ", word])

    def append(self, text: list[str] | None = None, *, newlines: int = 0) -> None:
        if len(self.hold_space) == 0:
            if text is not None:
                self._append_word_wrap(text)
            if newlines > 0:
                self.output.append("\n" * newlines)
                self.line_length = 0
        else:
            assert newlines == 0
            if text:
                self.hold_space[-1].extend(text)

    def push_hold_space(self) -> None:
        self.hold_space.append([])

    def pop_hold_space(self, join_char: str = " ") -> str:
        return join_char.join(self.hold_space.pop())

    def escape(self, inp: str) -> str:
        return inp

    def visit_section(self, node: nodes.section) -> None:
        self.section_depth += 1

    def depart_section(self, node: nodes.section) -> None:
        self.section_depth -= 1

    def visit_title(self, node: nodes.title) -> None:
        self.push_hold_space()

    def depart_title(self, node: nodes.title) -> None:
        title_text = self.pop_hold_space()
        sepchar = "==-^"[self.section_depth - 1]
        if self.section_depth == 1:
            self.append([sepchar * len(title_text)], newlines=1)
        self.append([title_text], newlines=1)
        self.append([sepchar * len(title_text)], newlines=1)
        if self.section_depth <= 2:
            self.append(newlines=1)

    def visit_paragraph(self, node: nodes.paragraph) -> None:
        if not self.after_list_item:
            self.append(newlines=1)
        self.after_list_item = False

    def depart_paragraph(self, node: nodes.paragraph) -> None:
        # in_bullet_list = bool(self.bullet_char)
        # self.append(["</p>"], newlines=1 if in_bullet_list else 2)
        self.append(newlines=1)

    def visit_Text(self, node: nodes.Text) -> None:
        text = node.astext()
        self.append(re.split(r"[ \n]+", text))

    def depart_Text(self, node: nodes.Text) -> None:
        pass

    def visit_strong(self, node: nodes.strong) -> None:
        self.push_hold_space()

    def depart_strong(self, node: nodes.strong) -> None:
        text = "".join(self.pop_hold_space())
        self.append([f"**{text}**"])

    def visit_emphasis(self, node: nodes.strong) -> None:
        self.push_hold_space()

    def depart_emphasis(self, node: nodes.strong) -> None:
        text = "".join(self.pop_hold_space())
        self.append([f"*{text}*"])

    def visit_ModelReferenceNode(self, node: ModelReferenceNode) -> None:
        pass

    def depart_ModelReferenceNode(self, node: ModelReferenceNode) -> None:
        self.append([f"~{node.ref}~"])

    def visit_reference(self, node: nodes.reference) -> None:
        self.push_hold_space()

    def depart_reference(self, node: nodes.reference) -> None:
        text = "".join(self.pop_hold_space())
        self.append([f"`{text}`_"])

    def visit_target(self, node: nodes.target) -> None:
        self.push_hold_space()

    def depart_target(self, node: nodes.target) -> None:
        text = "".join(self.pop_hold_space())
        self.append([f"_`{text}`"])

    def visit_bullet_list(self, node: nodes.bullet_list) -> None:
        assert self.line_length == 0  # just had a newline
        self.append(newlines=1)
        self.bullet_char.append(node["bullet"])

    def depart_bullet_list(self, node: nodes.bullet_list) -> None:
        self.bullet_char.pop()

    def visit_list_item(self, node: nodes.list_item) -> None:
        self.after_list_item = True
        self.append([self.bullet_char[-1] + self.indent[1:-1]])
        self.indent_level += 1

    def depart_list_item(self, node: nodes.list_item) -> None:
        self.indent_level -= 1

    def visit_system_message(self, _node: nodes.system_message) -> None:
        raise nodes.SkipChildren

    def depart_system_message(self, _node: nodes.system_message) -> None:
        pass

    def unknown_visit(self, node: nodes.Node) -> None:
        if isinstance(node, self.ignored_nodes):
            return
        print(f"Unknown visit {type(node)}")

    def unknown_departure(self, node: nodes.Node) -> None:
        if isinstance(node, self.ignored_nodes):
            return
        print(f"Unknown departure {type(node)}")


class MyWriter(writers.Writer):
    def translate(self) -> None:
        self.visitor = visitor = RstTranslator(self.document)
        self.document.walkabout(visitor)
        self.output = "".join(visitor.output)


def main() -> None:
    settings_overrides: dict[str, Any] = {
        "doctitle_xform": False,
        "use_latex_citations": True,
        # error reporting:
        "report_level": 2,
        "halt_level": 5,
        # "warning_stream": sys.stderr,
    }

    print(test_document)

    # old_line_text = Line.text

    # def line_text(self: Line, match: re.Match, somestrings: list[str], somename: str):
    #     out = old_line_text(self, match, somestrings, somename)
    #     print(f"Line.text({match.groups()}, {somestrings}, {somename}) -> {out}")
    #     return out

    # Line.text = line_text

    old_body_directive = Body.directive

    # old_body_directive(self=None, match="aap")
    def body_directive(self: Body, match: re.Match, **options) -> Any:
        print("XXX directive:", match.groups(), options)
        # directive = old_body_directive(self, match, **options)
        return []  # directive

    Body.directive = None
    # Body.directive = body_directive

    def directive(name: str, language, document) -> tuple[Directive | None, list[str]]:
        print(f"XXXX called for '{name}'")
        return None, []

    directives.directive = directive

    doctree: nodes.document = publish_doctree(
        source=test_document,
        source_class=io.StringInput,
        reader=Reader(),
        parser=MyParser(),
        settings_overrides=settings_overrides,
    )

    print(doctree.pformat())
    writer = MyWriter()
    out = publish_from_doctree(
        doctree,
        writer=writer,
        writer_name="my_writer",
        settings_overrides=settings_overrides,
    )
    print(type(out))
    print(out.decode("utf-8"))


if __name__ == "__main__":
    main()

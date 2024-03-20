from pathlib import Path
import re
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from difflib import unified_diff
import sys
from typing import Any, ClassVar

from docutils import io, nodes, writers
from docutils.core import publish_doctree, publish_from_doctree
from docutils.parsers.rst import Directive, Parser, directives
from docutils.parsers.rst.states import Inliner
from docutils.readers.standalone import Reader


@dataclass
class RstFormatterConfig:
    """Configuration for the rst_format function."""

    max_line_length: int = 120

    # everything matching this regex should not be broken because of the max line length
    no_line_break_regexes: list[re.Pattern] = field(default_factory=lambda: [re.compile(r"~[^~]*~")])

    # how to format titles. Two characters means above-and-below line.
    title_order: list[str] = field(default_factory=lambda: ["==", "=", "-", "^"])

    # add a newline after the title line if the heading is less than:
    newline_after_title: int = 2

    # no newline after ':' in a bulletlist
    no_newline_bulletlist = True


class NoLineBreakNode(nodes.Inline, nodes.TextElement):
    """Special formatting node that does nothing except prevent line breaks inside."""

    def __init__(self, text: str) -> None:
        super().__init__(text=text)

    def pformat(self, indent: str = "    ", level: int = 0):
        return f"{indent * level}NoLineBreak\n"


class DirectivePlaceholder(Directive, nodes.Node):
    """Special node used for any directives found."""

    class AllowAllOptions:
        """Option specification so we support all (possible) options."""

        def __bool__(self) -> bool:
            """Yes, we support options."""
            return True

        def __getitem__(self, _key: str) -> object:
            """Return conversion function for any key."""
            return lambda x: x

    has_content = True  # can have content
    optional_arguments = 999
    option_spec = AllowAllOptions()
    children = ()

    def run(self) -> list[nodes.Node]:
        """Return a tree node for this Directive. Just use this instance."""
        return [self]

    def pformat(self, indent: str = "    ", level: int = 0) -> str:
        """For formatted print."""
        return f"{indent * level}Directive {self.name}\n"


class RstParser(Parser):
    """Custom rst parser that will add the no_line_break_regexes from the config."""

    def __init__(self, config: RstFormatterConfig) -> None:
        """Construct RstParser."""
        inliner = Inliner()

        def model_ref_node_factory(match: re.Match, _lineno: int) -> list[nodes.Node]:
            return [NoLineBreakNode(match.group(0))]

        for regex in config.no_line_break_regexes:
            inliner.implicit_dispatch.append((regex, model_ref_node_factory))

        super().__init__(rfc2822=False, inliner=inliner)


class RstTranslator(nodes.NodeVisitor):
    """Visitor that will format rst according to a given configuration."""

    ignored_nodes = (nodes.document,)  # nodes that have no equivalent in rst
    non_breakable_nodes: ClassVar[dict[type, tuple[str, str]]] = {
        nodes.strong: ("**", "**"),
        nodes.emphasis: ("*", "*"),
        NoLineBreakNode: ("", ""),
        nodes.reference: ("`", "`_"),
        nodes.target: ("_`", "`"),
    }

    def __init__(self, document: nodes.document, config: RstFormatterConfig) -> None:
        """Construct RstTranslator."""
        super().__init__(document)
        self.output: list[str] = []  # the final output. Will be joined on return
        self.config = config

        # while inside something non-breakable we append to hold-space instead of output. When inside multiple
        # non-breakable tags we add another entry.
        self.hold_space: list[list[str]] = []  # inside something non-breakable
        self.line_length: int = 0  # where is my cursor

        self.indent_level = 0  # how many times have we entered a block
        self.indent = "  "  # how many spaces to add every time we enter a block

        self.section_depth = 0  # for the heading characters

        self.bullet_char: list[str] = []  # for bullet lists in bullet lists

        self.need_newline_before_paragraph_start = False

    def _append_word_wrap(self, text: list[str]) -> None:
        for word in text:
            if not word:
                continue
            if self.line_length + 1 + len(word) > self.config.max_line_length:
                self.append(newlines=1)
            if self.line_length == 0:
                indent = self.indent * self.indent_level
                self.line_length += len(indent) + len(word)
                self.output.extend([indent, word])
            else:
                self.line_length += 1 + len(word)
                if not word.startswith(tuple(",.")):
                    self.output.extend([" "])
                self.output.extend([word])

    def append(self, text: list[str] | None = None, *, newlines: int = 0) -> None:
        """Append text to output, unless inside a non-breakable element, then append to hold space."""
        if len(self.hold_space) == 0:
            if text is not None:
                self._append_word_wrap(text)
            if newlines > 0:
                self.output.append("\n" * newlines)
                self.line_length = 0
        else:
            assert newlines == 0  # not supported, not sure if we want to add newlines to the hold-space
            if text:
                self.hold_space[-1].extend(text)

    def enter_nonbreakable_element(self) -> None:
        """Add all text to hold-space instead of output."""
        self.hold_space.append([])

    def exit_nonbreakable_element(self, join_char: str = " ") -> str:
        """Return outer level of hold space, joined on join_char."""
        return join_char.join(self.hold_space.pop())

    def escape(self, inp: str) -> str:
        return inp

    def visit_section(self, _node: nodes.section) -> None:
        self.section_depth += 1

    def depart_section(self, _node: nodes.section) -> None:
        self.section_depth -= 1

    def visit_title(self, _node: nodes.title) -> None:
        self.enter_nonbreakable_element()

    def depart_title(self, _node: nodes.title) -> None:
        title_text = self.exit_nonbreakable_element()
        try:
            sep_chars = self.config.title_order[self.section_depth - 1]
        except IndexError as err:
            raise RuntimeError("Not enough title characters defined in 'title_order'") from err
        if len(sep_chars) == 2:
            self.append([sep_chars[0] * len(title_text)], newlines=1)
        self.append([title_text], newlines=1)
        self.append([sep_chars[-1] * len(title_text)], newlines=1)
        if self.section_depth <= self.config.newline_after_title:
            self.need_newline_before_paragraph_start = True

    def visit_paragraph(self, _node: nodes.paragraph) -> None:
        if self.need_newline_before_paragraph_start:
            self.append(newlines=1)
            self.need_newline_before_paragraph_start = False

    def depart_paragraph(self, _node: nodes.paragraph) -> None:
        self.append(newlines=1)  # end the current sentence
        self.need_newline_before_paragraph_start = True

    def visit_Text(self, node: nodes.Text) -> None:
        text = node.astext()
        self.append(re.split(r"[ \n]+", text))

    def depart_Text(self, _node: nodes.Text) -> None:
        pass

    def visit_bullet_list(self, node: nodes.bullet_list) -> None:
        if len(self.bullet_char) > 0 or self.need_newline_before_paragraph_start:
            self.append(newlines=1)
        self.bullet_char.append(node["bullet"])

    def depart_bullet_list(self, _node: nodes.bullet_list) -> None:
        self.bullet_char.pop()

    def visit_list_item(self, _node: nodes.list_item) -> None:
        self.append([self.bullet_char[-1] + self.indent[1:-1]])
        self.indent_level += 1
        self.need_newline_before_paragraph_start = False

    def depart_list_item(self, _node: nodes.list_item) -> None:
        self.indent_level -= 1

    def visit_system_message(self, _node: nodes.system_message) -> None:
        raise nodes.SkipChildren

    def depart_system_message(self, _node: nodes.system_message) -> None:
        pass

    def visit_DirectivePlaceholder(self, node: DirectivePlaceholder) -> None:
        assert self.line_length == 0
        self.append([f".. {node.name}::"] + node.arguments, newlines=1)
        self.indent_level += 1
        for key, value in sorted(node.options.items()):
            self.append([f":{key}:", value], newlines=1)

        if node.options or node.content:
            self.append(newlines=1)

        if node.content:
            self.append(list(node.content), newlines=1)

    def depart_DirectivePlaceholder(self, _node: DirectivePlaceholder) -> None:
        self.indent_level -= 1

    def unknown_visit(self, node: nodes.Node) -> None:
        if isinstance(node, self.ignored_nodes):
            return

        if type(node) in self.non_breakable_nodes:
            self.enter_nonbreakable_element()
            return

        print(f"Unknown visit {type(node)}")

    def unknown_departure(self, node: nodes.Node) -> None:
        if isinstance(node, self.ignored_nodes):
            return

        non_breakable = self.non_breakable_nodes.get(type(node))
        if non_breakable is not None:
            text = self.exit_nonbreakable_element()
            self.append([f"{non_breakable[0]}{text}{non_breakable[1]}"])
            return

        print(f"Unknown departure {type(node)}")


class RstFormattingWriter(writers.Writer):
    def __init__(self, config: RstFormatterConfig) -> None:
        super().__init__()
        self.config = config

    def translate(self) -> None:
        self.visitor = visitor = RstTranslator(self.document, config=self.config)
        self.document.walkabout(visitor)
        self.output = "".join(visitor.output)


@contextmanager
def monkeypatch_directives_handler() -> Generator[None, Any, None]:
    """Make sure that all directives in the rst are stored."""

    class MonkeyPatchedDirectiveHandler:
        def __contains__(self, key: str) -> bool:
            return True

        def __getitem__(self, item: str) -> type[Directive]:
            return DirectivePlaceholder

    old_directive_handler = directives._directives  # noqa: SLF001
    directives._directives = MonkeyPatchedDirectiveHandler()  # noqa: SLF001
    try:
        yield
    finally:
        directives._directives = old_directive_handler  # noqa: SLF001


def fix_multiline_headings(input_rst: str, config: RstFormatterConfig) -> str:
    chars = "".join(set("".join(config.title_order))).replace("^", "\\^").replace("-", "\\-")
    regex_str = r"^([CHARS]){3,}$".replace("CHARS", chars)
    compiled_regex = re.compile(regex_str, flags=re.MULTILINE)
    return compiled_regex.sub(r"\1\1\1\1", input_rst)


def format_rst(input_rst: str, config: RstFormatterConfig | None = None) -> str:
    """Convert the input rst to a re-formatted output."""
    if config is None:
        config = RstFormatterConfig()

    if config.no_newline_bulletlist:
        input_rst = input_rst.replace(":\n-", ":\n\n-")

    input_rst = fix_multiline_headings(input_rst, config)

    settings_overrides: dict[str, Any] = {
        "doctitle_xform": False,
        "use_latex_citations": True,
        # error reporting:
        "report_level": 5,
        "halt_level": 5,
        # "warning_stream": sys.stderr,
        "output_encoding": "unicode",
    }

    with monkeypatch_directives_handler():
        doctree: nodes.document = publish_doctree(
            source=input_rst,
            source_class=io.StringInput,
            reader=Reader(),
            parser=RstParser(config=config),
            settings_overrides=settings_overrides,
        )

        print(doctree.pformat())
        writer = RstFormattingWriter(config)
        out = publish_from_doctree(
            doctree,
            writer=writer,
            writer_name="rst_formatting_writer",
            settings_overrides=settings_overrides,
        )

    if config.no_newline_bulletlist:
        out = out.replace(":\n\n-", ":\n-")
    return out.lstrip("\n").rstrip("\n")


test_document = """

"""


def main() -> int:
    """Entrypoint."""
    try:
        rst_file = Path(sys.argv[1])
    except IndexError:
        print("Specify inputfile!")
        return -1
    content = rst_file.read_text()
    out = format_rst(content)

    def generate_unified_diff(str1: str, str2: str) -> str:
        diff = list(unified_diff(str1.splitlines(), str2.splitlines(), lineterm=""))
        return "\n".join(diff)

    print(generate_unified_diff(content, out))
    return content == out


if __name__ == "__main__":
    main()

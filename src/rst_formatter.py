"""Re-format rst files."""

from __future__ import annotations

import argparse
import re
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from difflib import unified_diff
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from docutils import io, nodes, writers
from docutils.core import publish_doctree, publish_from_doctree
from docutils.parsers.rst import Directive, Parser, directives
from docutils.parsers.rst.states import Body, Inliner
from docutils.readers.standalone import Reader

if TYPE_CHECKING:
    from collections.abc import Generator

    from docutils.statemachine import StringList


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

    # newline after ':' in a bullet list, rst specifies that a newline is needed before the first item
    newline_bullet_list: bool = False

    # for development, print the intermediate docutils node tree
    print_node_tree: bool = False

    @staticmethod
    def prepare_argparse(parser: argparse.ArgumentParser) -> None:
        """Add arguments corresponding to settings above."""
        parser.add_argument("--max_line_length", type=int, default=120, help="Maximum line length")
        parser.add_argument(
            "--no_line_break", nargs="+", default=[r"~[^~]*~"], help="Regex patterns that should not be broken"
        )
        parser.add_argument("--titles", nargs="+", default=["==", "=", "-", "^"], help="Title formatting characters")
        parser.add_argument("--newline_after_title", type=int, default=2, help="Add newline after major headings")
        parser.add_argument("--newline_bullet_list", action="store_true", help='Add newline after ":" in a bullet list')
        parser.add_argument("--print-parse-tree", action="store_true", help=argparse.SUPPRESS)

    @staticmethod
    def parse_argparse(args: argparse.Namespace) -> RstFormatterConfig:
        """Convert the parsed arguments to a RstFormatterConfig."""
        config = RstFormatterConfig()
        config.max_line_length = args.max_line_length
        if args.no_line_break:
            config.no_line_break_regexes = [re.compile(pattern) for pattern in args.no_line_break]
        if args.titles:
            config.title_order = args.titles
        config.newline_after_title = args.newline_after_title
        config.newline_bullet_list = args.newline_bullet_list
        config.print_node_tree = args.print_parse_tree
        return config


class NoLineBreakNode(nodes.Inline, nodes.TextElement):
    """Special formatting node that does nothing except prevent line breaks inside."""


class DirectivePlaceholder(Directive, nodes.Node):
    """Special node used for any directives found."""

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

    def get_transforms(self) -> list[Any]:
        """Suppress transforms."""
        return []


class RstTranslator(nodes.NodeVisitor):
    """Visitor that will format rst according to a given configuration."""

    ignored_nodes = (nodes.document, nodes.transition)  # nodes that have no equivalent in rst

    # nodes that are not re-formatted
    non_breakable_nodes: ClassVar[set[type]] = {
        nodes.citation_reference,
        nodes.emphasis,
        nodes.reference,
        nodes.strong,
        nodes.target,
        NoLineBreakNode,
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
            if newlines != 0:
                raise NotImplementedError  # not supported, not sure if we want to add newlines to the hold-space
            if text:
                self.hold_space[-1].extend(text)

    def enter_nonbreakable_element(self) -> None:
        """Add all text to hold-space instead of output."""
        self.hold_space.append([])

    def exit_nonbreakable_element(self, join_char: str = " ") -> str:
        """Return outer level of hold space, joined on join_char."""
        return join_char.join(self.hold_space.pop())

    def append_possible_newline(self) -> None:
        """Emit a newline if the previous node requested it."""
        if self.need_newline_before_paragraph_start:
            self.append(newlines=1)
            self.need_newline_before_paragraph_start = False

    def visit_target(self, _node: nodes.target) -> None:
        """Link-target."""
        self.enter_nonbreakable_element()

    def depart_target(self, node: nodes.target) -> None:
        """
        Link-target.

        Targets are documented as 'invisible', but if they are a hyperlink target or have children they must be
        rendered anyway.
        """
        self.exit_nonbreakable_element()
        if node.rawsource.startswith(".. _"):
            self.append_possible_newline()
            self.append([node.rawsource], newlines=1)
            self.need_newline_before_paragraph_start = True
        elif node.children:
            self.append([node.rawsource])

    def visit_section(self, _node: nodes.section) -> None:
        self.section_depth += 1

    def depart_section(self, _node: nodes.section) -> None:
        self.section_depth -= 1

    def visit_title(self, _node: nodes.title) -> None:
        self.append_possible_newline()
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
        self.append_possible_newline()

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

    def visit_citation(self, _node: nodes.citation) -> None:
        self.append_possible_newline()
        self.append([".."])

    def depart_citation(self, _node: nodes.citation) -> None:
        self.need_newline_before_paragraph_start = True

    def visit_label(self, _node: nodes.label) -> None:
        self.enter_nonbreakable_element()

    def depart_label(self, _node: nodes.label) -> None:
        text = self.exit_nonbreakable_element()
        self.append([f"[{text}]"])

    def visit_system_message(self, _node: nodes.system_message) -> None:
        raise nodes.SkipChildren

    def depart_system_message(self, _node: nodes.system_message) -> None:
        pass

    def visit_DirectivePlaceholder(self, node: DirectivePlaceholder) -> None:
        self.append_possible_newline()
        if self.line_length != 0:
            raise RuntimeError("Directive found while indented.")
        self.append([f".. {node.name}::", *node.arguments], newlines=1)
        self.indent_level += 1
        for key, value in sorted(node.options.items()):
            self.append([f":{key}:", value], newlines=1)

        if node.options and node.content:
            self.append(newlines=1)

        for line in node.content:
            self.append([line], newlines=1)

    def depart_DirectivePlaceholder(self, _node: DirectivePlaceholder) -> None:
        self.indent_level -= 1
        self.need_newline_before_paragraph_start = True

    def unknown_visit(self, node: nodes.Node) -> None:
        """Reached a node that has no specific visitor."""
        if isinstance(node, self.ignored_nodes):
            return

        if type(node) in self.non_breakable_nodes:
            self.enter_nonbreakable_element()
            return

        raise RuntimeError(f"Unknown visit {type(node)}")

    def unknown_departure(self, node: nodes.Node) -> None:
        """Leaving a node that has no specific visitor."""
        if isinstance(node, self.ignored_nodes):
            return

        if type(node) in self.non_breakable_nodes and isinstance(node, nodes.Element):
            self.exit_nonbreakable_element()
            self.append([node.rawsource])
            return

        raise RuntimeError(f"Unknown departure {type(node)}")


class RstFormattingWriter(writers.Writer):
    """A docutils Writer that emits rst."""

    def __init__(self, config: RstFormatterConfig) -> None:
        """Construct an RstFormattingWriter."""
        super().__init__()
        self.config = config

    def translate(self) -> None:
        """Do the work."""
        self.visitor = visitor = RstTranslator(self.document, config=self.config)
        self.document.walkabout(visitor)
        self.output = "".join(visitor.output)


def forgiving_parse_directive_block(
    self: Body, indented: StringList, _line_offset: int, _directive: type, _option_presets: dict
) -> tuple[list[str], dict[str, str], StringList, int]:
    """Parse a directive without accessing the directive."""
    # indented[0] is the list of arguments after the directive name
    arguments: list[str] = indented[0].strip().split()
    indented.trim_start()  # skip arguments

    options: dict[str, str] = {}
    option_regex = self.patterns["field_marker"]
    while indented:
        option_match = option_regex.match(indented[0])
        if not option_match:
            break
        key = option_match.group()  # including ':'
        value = indented[0][len(key) :]
        options[key[1:-2]] = value
        indented.trim_start()

    while indented and len(indented[-1].strip()) == 0:
        indented.trim_end()

    if indented and len(indented[0].strip()) == 0:
        indented.trim_start()  # blank line between options and content

    return arguments, options, indented, indented.parent_offset


@contextmanager
def monkeypatch_directives_handler() -> Generator[None, Any, None]:
    """
    Replace inner functions of docutils' rst parser to generate our own nodes.

    We replace:
    - The list of known directives ('_directives') with a dict-lookalike that always returns a DirectivePlaceHolder.
    - The directive parse function with our own, so we don't need to know whether or not the directive has options.
    """

    class MonkeyPatchedDirectiveHandler:
        def __contains__(self, key: str) -> bool:
            return True

        def __getitem__(self, item: str) -> type[Directive]:
            return DirectivePlaceholder

    old_directive_handler = directives._directives  # noqa: SLF001
    old_directive_parser = Body.parse_directive_block
    directives._directives = MonkeyPatchedDirectiveHandler()  # noqa: SLF001
    Body.parse_directive_block = forgiving_parse_directive_block
    try:
        yield
    finally:
        directives._directives = old_directive_handler  # noqa: SLF001
        Body.parse_directive_block = old_directive_parser


def fix_heading_line_length(input_rst: str, config: RstFormatterConfig) -> str:
    """
    Fix heading line length.

    Replace every line consisting 3-or-more heading-characters with exactly 4 heading characters.
    This will make docutils' rst parser construct the correct node tree, so we can emit the correct output later.
    """
    chars = "".join(set("".join(config.title_order))).replace("^", "\\^").replace("-", "\\-")
    regex_str = r"^([CHARS]){3,}$".replace("CHARS", chars)
    compiled_regex = re.compile(regex_str, flags=re.MULTILINE)
    return compiled_regex.sub(r"\1\1\1\1", input_rst)


def format_rst(input_rst: str, config: RstFormatterConfig | None = None) -> str:
    """Convert the input rst to a re-formatted output."""
    if config is None:
        config = RstFormatterConfig()

    if not config.newline_bullet_list:
        input_rst = re.sub(r":\n(\s*[-*] )", r":\n\n\1", input_rst)

    # fix case of forgetting a newline before a directive
    input_rst = re.sub(r"([^\n])(\n.. )", r"\1\n\2", input_rst)

    input_rst = fix_heading_line_length(input_rst, config)

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

        if config.print_node_tree:
            print(doctree.pformat())

        writer = RstFormattingWriter(config)
        out = publish_from_doctree(
            doctree,
            writer=writer,
            writer_name="rst_formatting_writer",
            settings_overrides=settings_overrides,
        )

    if not config.newline_bullet_list:
        out = re.sub(r":\n\n(\s*[-*] )", r":\n\1", out)
    return out.lstrip("\n").rstrip("\n")


def main(arguments: list[str] | None = None) -> int:
    """Entrypoint."""
    parser = argparse.ArgumentParser(description="Tool for formatting an rst file")
    parser.add_argument("input_file", type=Path, help="Input file to be processed")
    parser.add_argument("--check", "-c", action="store_true", help="Return 0 if no changes are needed")
    parser.add_argument("--diff", "-d", action="store_true", help="Perform a diff operation")
    parser.add_argument("--silent", "-s", action="store_true", help="Run in silent mode")
    RstFormatterConfig.prepare_argparse(parser)
    args = parser.parse_args(arguments if arguments is not None else sys.argv[1:])
    config = RstFormatterConfig.parse_argparse(args)

    rst_file = args.input_file
    content = rst_file.read_text()
    out = format_rst(content, config)

    def print_unless_silent(arg: str) -> None:
        if not args.silent:
            print(arg)

    if content == out:
        print_unless_silent("Nothing changed")
        return 0

    if args.diff:
        diff = list(unified_diff(content.splitlines(), out.splitlines(), lineterm=""))
        print_unless_silent("\n".join(diff))
        return 1

    if not args.check:
        print_unless_silent(f"Writing changes to '{rst_file}'")
        rst_file.write_text(out)
    else:
        print_unless_silent("File needs changes (but file left unchanged)")

    return 1


if __name__ == "__main__":
    sys.exit(main())

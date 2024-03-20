
import tempfile
from pathlib import Path

from rst2pdf.createpdf import RstToPdf

from docutils import io, nodes
from docutils.core import publish_doctree, publish_from_doctree
from docutils.readers.standalone import Reader as StandaloneReader


class DocReader(StandaloneReader):
    def new_document(self) -> nodes.document:
        out = super().new_document()
        out.transformer.unknown_reference_resolvers.append(reference_resolver)
        return out


def gen_output(doctree: nodes.document) -> None:
    with Path('out.pdf').open('wb') as outfile:
        RstToPdf().createPdf(
            doctree=doctree,
            output=outfile,
            compressed=False
        )

    with tempfile.NamedTemporaryFile('w') as templatefile:
        templatefile.write('%(body)s')
        templatefile.flush()
        doctreehtml = publish_from_doctree(
            doctree,
            writer_name='xhtml',
            settings_overrides={
                'output_encoding': 'unicode',
                'template': templatefile.name
            },
        )
    print(doctreehtml)


class PendingReferenceNode(nodes.Node):
    name: str
    refname: str

    children = ()

    def __init__(self, name: str, refname: str, children) -> None:
        self.name = name
        self.refname = refname
        self.children = children

    def pformat(self, indent: str = '    ', level: int = 0) -> str:
        return f"{indent*level}<PendingReferenceNode name='{self.name}' refname='{self.refname}'>\n"


def reference_resolver(node: nodes.Element) -> bool:
    print("Resolving references in:", node.pformat())
    node.replace_self(PendingReferenceNode(node['name'], node['refname'], node.children))
    is_resolved = True
    return is_resolved


def main() -> None:
    doctree: nodes.document = publish_doctree(
        source=None, source_path='testfile.rst',
        source_class=io.FileInput,
        reader=DocReader(),
        settings_overrides={
            'doctitle_xform': False,
            'use_latex_citations': True,
        })

    doctree.transformer.unknown_reference_resolvers.append(reference_resolver)

    print(doctree.pformat())

    # gen_output(doctree)


if __name__ == "__main__":
    main()

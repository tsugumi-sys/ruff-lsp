import unittest

from pygls.workspace import Document, Workspace

from ruff_lsp.complete import jedi_completion
from ruff_lsp.uris import from_fs_path

DOC_URI = from_fs_path(__file__)
DOC = """import os
print os.path.isabs("/tmp")
def hello():
    pass
def _a_hello():
    pass
class Hello():
    @property
    def world(self):
        return None
    def everyone(self, a, b, c=None, d=2):
        pass
print Hello().world
print Hello().every
def documented_hello():
    \"\"\"Sends a polite greeting\"\"\"
    pass
"""


class TestComplete(unittest.TestCase):
    def test_jedi_completion(self):
        workspace = Workspace("/ws")
        com_position = {"line": 1, "character": 15}
        doc = Document(DOC_URI, source=DOC)
        items = jedi_completion({}, workspace, doc, com_position)

        assert items
        labels = [i["label"] for i in items]
        assert "isfile(path)" in labels

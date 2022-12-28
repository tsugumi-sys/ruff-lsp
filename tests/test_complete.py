import math
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict, NamedTuple

from lsprotocol.types import CompletionItemKind, InsertTextFormat
from pygls.workspace import Document, Workspace

from ruff_lsp.complete import jedi_completion, jedi_completion_item_resolve
from ruff_lsp.uris import from_fs_path

PY2 = sys.version[0] == "2"
LINUX = sys.platform.startswith("linux")
CI = os.environ.get("CI")
LOCATION = os.path.realpath(os.path.join(os.getcwd(), os.path.dirname(__file__)))
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


class TypeCase(NamedTuple):
    document: str
    position: Dict
    label: str
    expected: CompletionItemKind


TYPE_CASES: Dict[str, TypeCase] = {
    "variable": TypeCase(
        document="test = 1\ntes",
        position={"line": 1, "character": 3},
        label="test",
        expected=CompletionItemKind.Variable,
    ),
    "function": TypeCase(
        document="def test():\n    pass\ntes",
        position={"line": 2, "character": 3},
        label="test()",
        expected=CompletionItemKind.Function,
    ),
    "keyword": TypeCase(
        document="fro",
        position={"line": 0, "character": 3},
        label="from",
        expected=CompletionItemKind.Keyword,
    ),
    "file": TypeCase(
        document='"' + __file__[:-2].replace('"', '\\"') + '"',
        position={"line": 0, "character": len(__file__) - 2},
        label=Path(__file__).name + '"',
        expected=CompletionItemKind.File,
    ),
    "module": TypeCase(
        document="import statis",
        position={"line": 0, "character": 13},
        label="statistics",
        expected=CompletionItemKind.Module,
    ),
    "class": TypeCase(
        document="KeyErr",
        position={"line": 0, "character": 6},
        label="KeyError",
        expected=CompletionItemKind.Class,
    ),
    "property": TypeCase(
        document=(
            "class A:\n"
            "    @property\n"
            "    def test(self):\n"
            "        pass\n"
            "A().tes"
        ),
        position={"line": 4, "character": 5},
        label="test",
        expected=CompletionItemKind.Property,
    ),
}


class TestComplete(unittest.TestCase):
    def setUp(self):
        self.workspace = Workspace("/ws")

    def tearDown(self):
        self.workspace = None

    def test_jedi_completion_type(self):
        for case in TYPE_CASES.values():
            doc = Document(DOC_URI, source=case.document)
            items = jedi_completion({}, {}, self.workspace, doc, case.position)
            items = {i["label"]: i for i in items}
            assert items[case.label]["kind"] == case.expected

    def test_jedi_completion(self):
        com_position = {"line": 1, "character": 15}
        doc = Document(DOC_URI, source=DOC)
        items = jedi_completion({}, {}, self.workspace, doc, com_position)

        assert items
        labels = [i["label"] for i in items]
        assert "isfile(path)" in labels

        # Test we don't throw with big character
        jedi_completion({}, {}, self.workspace, doc, {"line": 1, "character": 1000})

    def test_jedi_completion_resolve(self):
        # Over the blank line
        com_position = {"line": 8, "character": 0}
        doc = Document(DOC_URI, source=DOC)
        jedi_config = {"resolve_at_most": math.inf}
        completions = jedi_completion(
            jedi_config,
            {},
            self.workspace,
            doc,
            com_position,
        )

        items = {c["label"]: c for c in completions}
        documented_hello_item = items["documented_hello()"]

        assert "documentation" not in documented_hello_item
        assert "detail" not in documented_hello_item

        resolved_documented_hello = jedi_completion_item_resolve(
            {},
            completion_item=documented_hello_item,
        )
        expected_doc = {
            "kind": "markdown",
            "value": "```python\ndocumented_hello()\n```\n\n\nSends a polite greeting",
        }
        assert resolved_documented_hello["documentation"] == expected_doc

    def test_jedi_completion_with_fuzzy_enabled(self):
        jedi_config = {"fuzzy": True}
        com_position = {"line": 1, "character": 15}
        doc = Document(DOC_URI, source=DOC)
        items = jedi_completion(jedi_config, {}, self.workspace, doc, com_position)

        assert items

        expected = "commonprefix(m)"
        assert items[0]["label"] == expected

        # Test we don't throw with big character
        jedi_completion({}, {}, self.workspace, doc, {"line": 1, "character": 1000})

    def test_jedi_completion_resolve_at_most(self):
        # Over 'i' in os.path.isabs(...)
        com_position = {"line": 1, "character": 15}
        doc = Document(DOC_URI, source=DOC)
        jedi_config = {"resolve_at_most": 0}
        items = jedi_completion(jedi_config, {}, self.workspace, doc, com_position)
        labels = {i["label"] for i in items}
        assert "isabs" in labels

        # Resolve all items
        jedi_config["resolve_at_most"] = math.inf
        items = jedi_completion(jedi_config, {}, self.workspace, doc, com_position)
        labels = [i["label"] for i in items]
        assert "isfile(path)" in labels

    def test_jedi_completion_ordering(self):
        # Over the blank line
        com_position = {"line": 8, "character": 0}
        doc = Document(DOC_URI, source=DOC)
        jedi_config = {"resolve_at_most": math.inf}
        completions = jedi_completion(
            jedi_config, {}, self.workspace, doc, com_position
        )

        items = {c["label"]: c["sortText"] for c in completions}
        assert items["hello()"] < items["_a_hello()"]

    def test_jedi_property_completion(self):
        # Over the 'w' in 'print Hello().world'
        com_position = {"line": 18, "character": 15}
        doc = Document(DOC_URI, source=DOC)
        completions = jedi_completion({}, {}, self.workspace, doc, com_position)

        items = {c["label"]: c["sortText"] for c in completions}
        assert "world" in list(items.keys())[0]

    def test_jedi_method_completion(self):
        # Over the 'y' in 'print Hello().every'
        com_position = {"line": 20, "character": 19}
        doc = Document(DOC_URI, source=DOC)

        completion_capabilities = {"completionItem": {"snippetSupport": True}}
        jedi_config = {"include_params": True}

        completions = jedi_completion(
            jedi_config, completion_capabilities, self.workspace, doc, com_position
        )
        everyone_method = [
            completion
            for completion in completions
            if completion["label"] == "everyone(a, b, c, d)"
        ][0]

        # Ensure we only generate snippets for positional args
        assert everyone_method["insertTextFormat"] == InsertTextFormat.Snippet
        assert everyone_method["insertText"] == "everyone(${1:a}, ${2:b})$0"

        # Disable param snippets
        jedi_config["include_params"] = False

        completions = jedi_completion(
            jedi_config, completion_capabilities, self.workspace, doc, com_position
        )
        everyone_method = [
            completion
            for completion in completions
            if completion["label"] == "everyone(a, b, c, d)"
        ][0]

        assert "insertTextFormat" not in everyone_method
        assert everyone_method["insertText"] == "everyone"

    @unittest.skipIf(
        PY2 or (sys.platform.startswith("linux") and CI is not None),
        "Test in Python 3 and not on CIs on Linux because wheels don't work on them.",
    )
    def test_pyqt_jedi_completion(self):
        # Over 'QA' in 'from PyQt5.QtWidgets import QApplication'
        doc_pyqt = "from PyQt5.QtWidgets import QA"
        com_position = {"line": 0, "character": len(doc_pyqt)}
        doc = Document(DOC_URI, source=doc_pyqt)
        completions = jedi_completion({}, {}, self.workspace, doc, com_position)

        assert completions is not None

    def test_numpy_completions(self):
        doc_numpy = "import numpy as np; np."
        com_position = {"line": 0, "character": len(doc_numpy)}
        doc = Document(DOC_URI, source=doc_numpy)
        items = jedi_completion({}, {}, self.workspace, doc, com_position)

        assert items
        assert any("array" in i["label"] for i in items)

    def test_pandas_completions(self):
        doc_pandas = "import pandas as pd; pd."
        com_position = {"line": 0, "character": len(doc_pandas)}
        doc = Document(DOC_URI, source=doc_pandas)
        items = jedi_completion({}, {}, self.workspace, doc, com_position)

        assert items
        assert any("DataFrame" in i["label"] for i in items)

    def test_matplotlib_completions(self):
        doc_mpl = "import matplotlib.pyplot as plt; plt."
        com_position = {"line": 0, "character": len(doc_mpl)}
        doc = Document(DOC_URI, source=doc_mpl)
        items = jedi_completion({}, {}, self.workspace, doc, com_position)

        assert items
        assert any("plot" in i["label"] for i in items)

    def test_snippets_completion(self):
        doc_snippets = "from collections import defaultdict \na=defaultdict"
        com_position = {"line": 0, "character": 35}
        doc = Document(DOC_URI, source=doc_snippets)
        completion_capabilities = {"completionItem": {"snippetSupport": True}}
        jedi_config = {"include_params": True}
        completions = jedi_completion(
            jedi_config, completion_capabilities, self.workspace, doc, com_position
        )
        assert completions[0]["insertText"] == "defaultdict"

        com_position = {"line": 1, "character": len(doc_snippets)}
        completions = jedi_completion(
            jedi_config, completion_capabilities, self.workspace, doc, com_position
        )
        assert completions[0]["insertText"] == "defaultdict($0)"
        assert completions[0]["insertTextFormat"] == InsertTextFormat.Snippet

    def test_snippets_completion_at_most(self):
        doc_snippets = "from collections import defaultdict \na=defaultdict"
        doc = Document(DOC_URI, source=doc_snippets)
        completion_capabilities = {"completionItem": {"snippetSupport": True}}
        jedi_config = {"include_params": True, "resolve_at_most": 0}
        com_position = {"line": 1, "character": len(doc_snippets)}
        completions = jedi_completion(
            jedi_config, completion_capabilities, self.workspace, doc, com_position
        )
        assert completions[0]["insertText"] == "defaultdict"
        assert not completions[0].get("insertTextFormat", None)

    def test_completion_with_class_objects(self):
        doc_text = "class FOOBAR(Object): pass \nFOOB"
        com_position = {"line": 1, "character": 4}
        doc = Document(DOC_URI, source=doc_text)
        completion_capabilities = {"completionItem": {"snippetSupport": True}}
        jedi_config = {"include_params": True, "include_class_objects": True}
        completions = jedi_completion(
            jedi_config, completion_capabilities, self.workspace, doc, com_position
        )

        assert len(completions) == 2

        assert completions[0]["label"] == "FOOBAR"
        assert completions[0]["kind"] == CompletionItemKind.Class

        assert completions[1]["label"] == "FOOBAR object"
        assert completions[1]["kind"] == CompletionItemKind.TypeParameter

    def test_completion_with_function_object(self):
        doc_text = "def foobar(): pass\nfoob"
        com_position = {"line": 1, "character": 4}
        doc = Document(DOC_URI, source=doc_text)
        completion_capabilities = {"completionItem": {"snippetSupport": True}}
        jedi_config = {"include_params": True, "include_function_objects": True}
        completions = jedi_completion(
            jedi_config, completion_capabilities, self.workspace, doc, com_position
        )

        assert len(completions) == 2

        assert completions[0]["label"] == "foobar()"
        assert completions[0]["kind"] == CompletionItemKind.Function

        assert completions[1]["label"] == "foobar() object"
        assert completions[1]["kind"] == CompletionItemKind.TypeParameter

    def test_snippet_parsing(self):
        doc_text = "divmod"
        com_position = {"line": 0, "character": 6}
        doc = Document(DOC_URI, source=doc_text)
        completion_capabilities = {"completionItem": {"snippetSupport": True}}
        jedi_config = {"include_params": True}
        completions = jedi_completion(
            jedi_config, completion_capabilities, self.workspace, doc, com_position
        )

        out = "divmod(${1:x}, ${2:y})$0"
        assert completions[0]["insertText"] == out

    def test_multiline_import_snippets(self):
        doc_text = "from datetime import(\n date,\n datetime)\na=date"
        doc = Document(DOC_URI, source=doc_text)
        completion_capabilities = {"completionItem": {"snippetSupport": True}}
        jedi_config = {"include_params": True}

        com_position = {"line": 1, "character": 5}
        completions = jedi_completion(
            jedi_config, completion_capabilities, self.workspace, doc, com_position
        )
        assert completions[0]["insertText"] == "date"

        com_position = {"line": 2, "character": 9}
        completions = jedi_completion(
            jedi_config, completion_capabilities, self.workspace, doc, com_position
        )
        assert completions[0]["insertText"] == "datetime"

    def test_multiline_snippets(self):
        doc_text = "from datetime import\\\n date,\\\n datetime \na=date"
        doc = Document(DOC_URI, source=doc_text)
        completion_capabilities = {"completionItem": {"snippetSupport": True}}
        jedi_config = {"include_params": True}

        com_position = {"line": 1, "character": 5}
        completions = jedi_completion(
            jedi_config, completion_capabilities, self.workspace, doc, com_position
        )
        assert completions[0]["insertText"] == "date"

        com_position = {"line": 2, "character": 9}
        completions = jedi_completion(
            jedi_config, completion_capabilities, self.workspace, doc, com_position
        )
        assert completions[0]["insertText"] == "datetime"

    def test_multistatement_snippet(self):
        completion_capabilities = {"completionItem": {"snippetSupport": True}}
        jedi_config = {"include_params": True}

        doc_text = "a = 1; from datetime import date"
        doc = Document(DOC_URI, source=doc_text)
        com_position = {"line": 0, "character": len(doc_text)}
        completions = jedi_completion(
            jedi_config, completion_capabilities, self.workspace, doc, com_position
        )
        assert completions[0]["insertText"] == "date"

        doc_text = "from math import fmod; a = fmod"
        doc = Document(DOC_URI, source=doc_text)
        com_position = {"line": 0, "character": len(doc_text)}
        completions = jedi_completion(
            jedi_config, completion_capabilities, self.workspace, doc, com_position
        )
        assert completions[0]["insertText"] == "fmod(${1:x}, ${2:y})$0"

    def test_jedi_completion_extra_paths(self):
        # Create a tempfile with some content and pass to extra_paths
        temp_doc_content = """
def spam():
    pass
"""
        p = tempfile.mkdtemp("extra_path")
        extra_paths = [str(p)]
        with open(os.path.join(p, "foo.py"), "w") as f:
            f.write(temp_doc_content)

        # Content of doc to test completion
        doc_content = """import foo
foo.s"""
        doc = Document(DOC_URI, source=doc_content)

        # After 'foo.s' without extra paths
        com_position = {"line": 1, "character": 5}
        completions = jedi_completion({}, {}, self.workspace, doc, com_position)
        assert completions is None

        # Update config extra paths
        jedi_config = {"extra_paths": extra_paths}

        # After 'foo.s' with extra paths
        completions = jedi_completion(
            jedi_config, {}, self.workspace, doc, com_position
        )
        assert completions[0]["label"] == "spam()"

    @unittest.skipIf(PY2 or not LINUX or not CI, "tested on linux and python3 only")
    def test_jedi_completion_environment(self):
        # Content of doc to text completion
        doc_content = """import logh"""
        doc = Document(DOC_URI, source=doc_content)

        # After 'import logh' with default environment
        com_position = {"line": 0, "character": 11}
        assert os.path.isdir("/tmp/pyenv")

        jedi_config = {"environment": None}
        completions = jedi_completion(
            jedi_config, {}, self.workspace, doc, com_position
        )
        assert completions is None

        # Update config extra environment
        env_path = "/tmp/pyenv/bin/python"
        jedi_config = {"environment": env_path}

        # After 'import logh' with new environment
        completions = jedi_completion(
            jedi_config, {}, self.workspace, doc, com_position
        )
        assert completions[0]["label"] == "loghub"

        resolved = jedi_completion_item_resolve({}, completions[0])
        assert "changelog generator" in resolved["documentation"]["value"].lower()

    def test_document_path_completions(self):
        # Create a dummy module out of the workspace's root_path and try to get
        # completions for it in another file placed next to it.
        doc_content = """
def foo():
    pass
"""
        p = tempfile.mkdtemp("module")
        with open(os.path.join(p, "mymodule.py"), "w") as f:
            f.write(doc_content)

        # Content of doc to test completion
        doc_content = """import mymodule
mymodule.f"""
        doc_path = os.path.join(p, "myfile.py")
        doc_uri = from_fs_path(doc_path)
        doc = Document(doc_uri, doc_content)

        com_position = {"line": 1, "character": 10}
        completions = jedi_completion({}, {}, self.workspace, doc, com_position)
        assert completions[0]["label"] == "foo()"

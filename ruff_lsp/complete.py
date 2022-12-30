import os
import re
from typing import Any, Dict, List, Optional

import docstring_to_markdown
import jedi
import parso
from lsprotocol.types import CompletionItem, CompletionItemKind, Position
from pygls.workspace import Document, Workspace

from ruff_lsp.resolver import LABEL_RESOLVER, SNIPPET_RESOLVER

AUTO_IMPORT_MODULES = "auto_import_modules"
DEFAULT_AUTO_IMPORT_MODULES = ["numpy"]
JEDI_ENVIRONMENTS = {}

JEDI_SHARED_DATA = {}

###
# Completion with jedi
# Borrow code from https://github.com/python-lsp/python-lsp-server/blob/develop/pylsp/plugins/jedi_completion.py
###
def jedi_completion(
    jedi_config: Dict,
    completion_capabilities: Dict,
    workspace: Workspace,
    document: Document,
    position: Position,
):
    resolve_eagerly = jedi_config.get("eager", False)
    code_position = position_to_jedi_linecolumn(document, position)

    completions = jedi_script(
        jedi_config, workspace, document, use_document_path=True
    ).complete(**code_position, fuzzy=jedi_config.get("fuzzy", False))

    if not completions:
        return None

    item_capabilities = completion_capabilities.get("completionItem", {})
    snippet_support = item_capabilities.get("snippetSupport")
    supported_markup_kinds = item_capabilities.get("documentationFormat", ["markdown"])
    preferred_markup_kind = choose_markup_kind(supported_markup_kinds)

    should_include_params = jedi_config.get("include_params")
    should_include_class_objects = jedi_config.get("include_class_objects", False)
    should_include_function_objects = jedi_config.get("include_function_objects", False)

    max_to_resolve = jedi_config.get("resolve_at_most", 25)
    modules_to_cache_for = jedi_config.get("cache_for", None)
    if modules_to_cache_for is not None:
        LABEL_RESOLVER.cached_modules = modules_to_cache_for
        SNIPPET_RESOLVER.cached_modules = modules_to_cache_for

    include_params = (
        snippet_support and should_include_params and use_snippets(document, position)
    )
    include_class_objects = (
        snippet_support
        and should_include_class_objects
        and use_snippets(document, position)
    )
    include_function_objects = (
        snippet_support
        and should_include_function_objects
        and use_snippets(document, position)
    )

    ready_completions = [
        _format_completion(
            c,
            markup_kind=preferred_markup_kind,
            include_params=include_params if c.type in ["class", "function"] else False,
            resolve=resolve_eagerly,
            resolve_label_or_snippet=(i < max_to_resolve),
        )
        for i, c in enumerate(completions)
    ]

    if include_class_objects:
        for i, c in enumerate(completions):
            if c.type == "class":
                completion_dict = _format_completion(
                    c,
                    markup_kind=preferred_markup_kind,
                    include_params=False,
                    resolve=resolve_eagerly,
                    resolve_label_or_snippet=(i < max_to_resolve),
                )
                completion_dict["kind"] = CompletionItemKind.TypeParameter
                completion_dict["label"] += " object"
                ready_completions.append(completion_dict)

    if include_function_objects:
        for i, c in enumerate(completions):
            if c.type == "function":
                completion_dict = _format_completion(
                    c,
                    markup_kind=preferred_markup_kind,
                    include_params=False,
                    resolve=resolve_eagerly,
                    resolve_label_or_snippet=(i < max_to_resolve),
                )
                completion_dict["kind"] = CompletionItemKind.TypeParameter
                completion_dict["label"] += " object"
                ready_completions.append(completion_dict)

    for completion_dict in ready_completions:
        completion_dict["data"] = {"doc_uri": document.uri}

    JEDI_SHARED_DATA["LAST_JEDI_COMPLETIONS"] = {
        completion["label"]: (completion, data)
        for completion, data in zip(ready_completions, completions)
    }

    return ready_completions or None


###
# completion item resolve
###
def jedi_completion_item_resolve(
    completion_capabilities: Dict,
    completion_item: CompletionItem,
):
    """Resolve formatted completion for given non-resolved completion"""
    shared_data = JEDI_SHARED_DATA["LAST_JEDI_COMPLETIONS"].get(completion_item.label)

    item_capabilities = completion_capabilities.get("completionItem", {})
    supported_markup_kinds = item_capabilities.get("documentationFormat", ["markdown"])
    preferred_markup_kind = choose_markup_kind(supported_markup_kinds)

    if shared_data:
        completion, data = shared_data
        return _resolve_completion(completion, data, markup_kind=preferred_markup_kind)
    return completion_item


###
# code borrowed from https://github.com/python-lsp/python-lsp-server/blob/develop/pylsp/_utils.py
###
SERVER_SUPPORTED_MARKUP_KINDS = ("markdown", "plaintext")


def choose_markup_kind(client_supported_markup_kinds: List[str]) -> str:
    """Choose a markup kind supported by both client and the server.

    This gives priority to the markup kinds provided earlier on the
    client preference list.
    """
    for kind in client_supported_markup_kinds:
        if kind in SERVER_SUPPORTED_MARKUP_KINDS:
            return kind
    return "markdown"


###
# code borrowed from https://github.com/python-lsp/python-lsp-server/blob/develop/pylsp/workspace.py
###
def position_to_jedi_linecolumn(document: Document, position: Position) -> Dict:
    """
    Convert the LSP format 'line', 'character' to Jedi's 'line' to 'column'

    https://microsoft.github.io/language-server-protocol/specification#position
    """
    code_position = {}
    if position:
        code_position = {
            "line": position.line + 1,
            "column": clip_column(position.character, document.lines, position.line),
        }
    return code_position


def clip_column(column, lines, line_number):
    """
    Normalise the position as per the LSP that accepts character positions > line length
    https://microsoft.github.io/language-server-protocol/specification#position
    """
    max_column = (
        len(lines[line_number].rstrip("\r\n")) if len(lines) > line_number else 0
    )
    return min(column, max_column)


def jedi_script(
    jedi_config: Dict,
    workspace: Workspace,
    document: Document,
    position: Optional[Position] = None,
    use_document_path: bool = False,
) -> jedi.Project:
    extra_paths = []
    environment_path = None
    env_vars = None

    if jedi_config is not None:
        jedi_config[AUTO_IMPORT_MODULES] = jedi_config.get(
            AUTO_IMPORT_MODULES, DEFAULT_AUTO_IMPORT_MODULES
        )

        environment_path = jedi_config.get("environment")
        extra_paths = jedi_config.get("extra_paths", [])
        env_vars = jedi_config.get("env_vars")

    # Drop PYTHONPATH from env_vars before creating the environment because that makes
    # Jedi throw an error.
    if env_vars is None:
        env_vars = os.environ.copy()
    env_vars.pop("PYTHONPATH", None)

    environment = _get_environment(environment_path, env_vars=env_vars)
    sys_path = environment.get_sys_path() + extra_paths
    project_path = workspace.root_path

    if use_document_path:
        sys_path += [os.path.normpath(os.path.dirname(document.path))]

    kwargs = {
        "code": document.source,
        "path": document.path,
        "environment": environment,
        "project": jedi.Project(path=project_path, sys_path=sys_path),
    }

    if position:
        kwargs += position_to_jedi_linecolumn(position)

    return jedi.Script(**kwargs)


def _get_environment(
    workspace: Workspace,
    environment_path: Optional[str] = None,
    env_vars: Optional[Any] = None,
) -> jedi.api.environment.Environment:
    if environment_path is None:
        environment = jedi.api.environment.get_cached_default_environment()
    else:
        if environment_path in JEDI_ENVIRONMENTS:
            environment = JEDI_ENVIRONMENTS[environment_path]
        else:
            environment = jedi.api.environment.create_environment(
                path=environment_path, safe=False, en_vars=env_vars
            )
            JEDI_ENVIRONMENTS[environment_path] = environment
    return environment


_TYPE_MAP = {
    "module": CompletionItemKind.Module,
    "namespace": CompletionItemKind.Module,  # to be added in Jedi 0.18+
    "class": CompletionItemKind.Class,
    "instance": CompletionItemKind.Reference,
    "function": CompletionItemKind.Function,
    "param": CompletionItemKind.Variable,
    "path": CompletionItemKind.File,
    "keyword": CompletionItemKind.Keyword,
    "property": CompletionItemKind.Property,  # added in Jedi 0.18
    "statement": CompletionItemKind.Variable,
}


def _format_completion(
    d,
    markup_kind: str,
    include_params=True,
    resolve=False,
    resolve_label_or_snippet=False,
):
    completion = {
        "label": _label(d, resolve_label_or_snippet),
        "kind": _TYPE_MAP.get(d.type),
        "sort_text": _sort_text(d),
        "insert_text": d.name,
    }

    if resolve:
        completion = _resolve_completion(completion, d, markup_kind)

    if d.type == "path":
        path = os.path.normpath(d.name)
        path = path.replace("\\", "\\\\")
        path = path.replace("/", "\\/")
        completion["insert_text"] = path

    if include_params and not is_exception_class(d.name):
        snippet = _snippet(d, resolve_label_or_snippet)
        completion.update(snippet)

    return completion


def _resolve_completion(completion, d, markup_kind: str):
    # pylint: disable=broad-except
    completion["detail"] = _detail(d)
    try:
        docs = format_docstring(
            d.docstring(raw=True),
            signatures=[signature.to_string() for signature in d.get_signatures()],
            markup_kind=markup_kind,
        )
    except Exception:
        docs = ""
    completion["documentation"] = docs
    return completion


###
# Code borrowed from https://github.com/python-lsp/python-lsp-server/blob/develop/pylsp/_utils.py
###
def format_docstring(
    contents: str, markup_kind: str, signatures: Optional[List[str]] = None
):
    """Transform the provided docstring into a MarkupContent object.

    If `markup_kind` is 'markdown' the docstring will get converted to
    markdown representation using `docstring-to-markdown`; if it is
    `plaintext`, it will be returned as plain text.
    Call signatures of functions (or equivalent code summaries)
    provided in optional `signatures` argument will be prepended
    to the provided contents of the docstring if given.
    """
    if not isinstance(contents, str):
        contents = ""

    if markup_kind == "markdown":
        try:
            value = docstring_to_markdown.convert(contents)
            return {"kind": "markdown", "value": value}
        except docstring_to_markdown.UnknownFormatError:
            value = escape_markdown(contents)

        if signatures:
            value = wrap_signature("\n".join(signatures)) + "\n\n" + value

        return {"kind": "markdown", "value": value}

    value = contents
    if signatures:
        value = "\n".join(signatures) + "\n\n" + value
    return {"kind": "plaintext", "value": escape_plain_text(value)}


def _label(definition, resolve=False):
    if not resolve:
        return definition.name
    sig = LABEL_RESOLVER.get_or_create(definition)
    if sig:
        return sig
    return definition.name


def _snippet(definition, resolve=False):
    if not resolve:
        return {}
    snippet = SNIPPET_RESOLVER.get_or_create(definition)
    return snippet


def escape_plain_text(contents: str) -> str:
    """
    Format plain text to display nicely in environments which do not respect
    whitespaces.
    """
    contents = contents.replace("\t", "\u00A0" * 4)
    contents = contents.replace("  ", "\u00A0" * 2)
    return contents


def escape_markdown(contents: str) -> str:
    """
    Format plain text to display nicely in Markdown environment.
    """
    # escape markdown syntax
    contents = re.sub(r"([\\*_#[\]])", r"\\\1", contents)
    # preserve white space characters
    contents = escape_plain_text(contents)
    return contents


def wrap_signature(signature):
    return "```python\n" + signature + "\n```\n"


def _detail(definition):
    try:
        return definition.parent().full_name or ""
    except AttributeError:
        return definition.full_name or ""


def _sort_text(definition):
    """Ensure builtins apper at the bottom.
    Description is of format <type>: <module>.<item>
    """
    prefix = "z{}" if definition.name.startswith("_") else "a{}"
    return prefix.format(definition.name)


def is_exception_class(name):
    try:
        return name in [cls.__name__ for cls in Exception.__subclasses__()]
    except AttributeError:
        return False


# Types of parso nodes for which snippet is not included in the completion
_IMPORTS = ("import_name", "import_from")

# Types of parso node for errors
_ERRORS = ("error_node",)


def use_snippets(document: Document, position: Position):
    """
    Determine if it's necessary to return snippets in code completions.

    This returns `False` if a completion is being requested on an import
    statement, `True` otherwise.
    """
    line = position.line
    lines = document.source.split("\n", line)
    act_lines = [lines[line][: position.character]]
    line -= 1
    last_character = ""
    while line > -1:
        act_line = lines[line]
        if (
            act_line.rstrip().endswith("\\")
            or act_line.rstrip().endswith("(")
            or act_line.rstrip().endswith(",")
        ):
            act_lines.insert(0, act_line)
            line -= 1
            if act_line.rstrip().endswith("("):
                last_character = ")"

        else:
            break
    if "(" in act_lines[-1].strip():
        last_character = ")"
    code = "\n".join(act_lines).rsplit(";", maxsplit=1)[-1].strip() + last_character
    tokens = parso.parse(code)
    expr_type = tokens.children[0].type
    return expr_type not in _IMPORTS and not (expr_type in _ERRORS and "import" in code)


# def _sys_path(environment_path: Optional[str] = None, env_vars: Optional[Any] = None):
#     path = list(EXTRA_SYS_PATH)
#     environment = _get_environment(environment_path, env_vars)
#     path.extend(environment.get_sys_path())
#     return path

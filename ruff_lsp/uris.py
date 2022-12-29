###
# Utils referenced from https://github.com/python-lsp/python-lsp-server/blob/develop/pylsp/uris.py
##
import os
import re
from urllib import parse

IS_WIN = os.name == "nt"
RE_DRIVE_LETTER_PATH = re.compile(r"^\/[a-zA-Z]:")


def urlparse(uri):
    """Parse and decode the parts of a URI."""
    scheme, netloc, path, params, query, fragment = parse.urlparse(uri)
    return (
        parse.unquote(scheme),
        parse.unquote(netloc),
        parse.unquote(path),
        parse.unquote(params),
        parse.unquote(query),
        parse.unquote(fragment),
    )


def urlunparse(parts):
    """Unparse and encode parts of a URI."""
    scheme, netloc, path, params, query, fragment = parts

    # Avoid encoding the windows drive letter colon
    if RE_DRIVE_LETTER_PATH.match(path):
        quoted_path = path[:3] + parse.quote(path[3:])
    else:
        quoted_path = parse.quote(path)

    return parse.urlunparse(
        (
            parse.quote(scheme),
            parse.quote(netloc),
            quoted_path,
            parse.quote(params),
            parse.quote(query),
            parse.quote(fragment),
        )
    )


def from_fs_path(path):
    """Returns a URI for the given filesystem path."""
    scheme = "file"
    params, query, fragment = "", "", ""
    path, netloc = _normalize_win_path(path)
    return urlunparse((scheme, netloc, path, params, query, fragment))


def _normalize_win_path(path):
    netloc = ""

    # normalize to fwd-slashes on windows,
    # on other systems bwd-slaches are valid
    # filename character, eg /f\oo/ba\r.txt
    if IS_WIN:
        path = path.replace("\\", "/")

    # check for authority as used in UNC shares
    # or use the path as given
    if path[:2] == "//":
        idx = path.index("/", 2)
        if idx == -1:
            netloc = path[2:]
        else:
            netloc = path[2:idx]
            path = path[idx:]

    # Ensure that path starts with a slash
    # or that it is at least a slash
    if not path.startswith("/"):
        path = "/" + path

    # Normalize drive paths to lower case
    if RE_DRIVE_LETTER_PATH.match(path):
        path = path[0] + path[1].lower() + path[2:]

    return path, netloc

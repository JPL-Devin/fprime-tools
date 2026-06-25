"""fprime.fpp.impl_merge: Merge generated implementation templates into user files

Provides the logic behind ``fprime-util impl --auto-merge``. After
``fpp-to-cpp --template`` regenerates the ``*.template.{hpp,cpp}`` files for a
component, this module splices any *newly generated* member functions (port
handlers, command handlers, overflow hooks, state-machine action/guard
implementations, ...) into the user's existing ``*.{hpp,cpp}`` implementation
files, without disturbing the code the user has already written.

The merge is intentionally **additive only**: functions that already exist in
the user file (matched by name) are never modified, reordered, or removed. When
a function exists in both the template and the user file but its parameter types
differ (i.e. the model signature changed), a warning is emitted so the user can
update the implementation by hand.

The parsing is regex/structure based. It relies on the very regular shape of the
code emitted by ``fpp-to-cpp`` (and preserved by ``clang-format``):

  * Members are grouped under banner sections of the form::

        // ----------------------------------------------------------------------
        // <Section title>
        // ----------------------------------------------------------------------

  * In the ``.cpp`` file, definitions are written as
    ``<ReturnType> <ClassName> ::<funcName>(<params>) { <body> }``. The impl
    class name is the component name, so the qualifier ``<ClassName> ::`` matches
    the user's file verbatim.
  * In the ``.hpp`` file, declarations are written as ``<ReturnType>
    <funcName>(<params>) [override] [const];`` under ``public:`` / ``private:``
    access tags, each preceded by a ``//!`` doc comment.

@author Devin
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# A banner "rule" line, e.g. "    // ----------------------------------------"
_BANNER_RULE_RE = re.compile(r"^[ \t]*//\s*-{5,}\s*$")
# An include directive line
_INCLUDE_RE = re.compile(r"^[ \t]*#\s*include\b.*$", re.MULTILINE)


@dataclass
class Function:
    """A single parsed member function (declaration or definition)."""

    name: str
    """Function identifier used as the merge key (ctor == class name,
    dtor == ``~`` + class name)."""

    text: str
    """Full source text of the function block, including any leading comment."""

    param_types: List[str]
    """Normalized list of parameter types, used for signature-drift detection."""

    section: str
    """Title of the banner section the function belongs to (``""`` if none)."""

    start: int
    """Character offset of the start of the block in the source."""

    end: int
    """Character offset just past the end of the block in the source."""


@dataclass
class MergeResult:
    """Outcome of merging a single file."""

    text: Optional[str]
    """The merged file contents, or ``None`` if nothing changed."""

    added: List[str] = field(default_factory=list)
    """Names of functions inserted into the user file."""

    drifted: List[str] = field(default_factory=list)
    """Names of functions whose parameter types differ between template and
    user file (signature drift)."""

    added_includes: List[str] = field(default_factory=list)
    """Include directives added to the user file."""


# ---------------------------------------------------------------------------
# Low-level scanning helpers
# ---------------------------------------------------------------------------


def _skip_string(text: str, idx: int) -> int:
    """Given the index of an opening quote, return the index just past the
    matching closing quote."""
    quote = text[idx]
    i = idx + 1
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == quote:
            return i + 1
        i += 1
    return n


def _match_delimiter(text: str, open_idx: int, open_ch: str, close_ch: str) -> int:
    """Return the index of the delimiter matching the one at ``open_idx``.

    Skips over ``//`` and ``/* */`` comments and string/char literals so that
    delimiters appearing inside them are ignored.
    """
    depth = 0
    i = open_idx
    n = len(text)
    while i < n:
        c = text[i]
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            nl = text.find("\n", i)
            i = n if nl == -1 else nl
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        if c in ('"', "'"):
            i = _skip_string(text, i)
            continue
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _line_start(text: str, idx: int) -> int:
    """Return the offset of the start of the line containing ``idx``."""
    nl = text.rfind("\n", 0, idx)
    return 0 if nl == -1 else nl + 1


def _normalize_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _strip_param_comment(param: str) -> str:
    """Remove a trailing ``//!< ...`` doc comment from a parameter."""
    idx = param.find("//")
    return param[:idx] if idx != -1 else param


def _split_top_level(text: str, sep: str) -> List[str]:
    """Split ``text`` on ``sep`` characters that are not nested inside
    ``()``/``<>``/``[]`` or string literals."""
    parts: List[str] = []
    depth = 0
    start = 0
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in ('"', "'"):
            i = _skip_string(text, i)
            continue
        if c in "(<[":
            depth += 1
        elif c in ")>]":
            depth -= 1
        elif c == sep and depth == 0:
            parts.append(text[start:i])
            start = i + 1
        i += 1
    parts.append(text[start:])
    return parts


def _normalize_param_type(type_str: str) -> str:
    """Normalize a parameter type for signature comparison.

    Top-level ``const`` on a by-value parameter is not part of the function
    signature in C++, so it is stripped to avoid spurious drift warnings when a
    user adds/removes ``const`` on value parameters. ``const`` that binds to a
    pointer/reference target (e.g. ``const T&``) is meaningful and kept.
    """
    type_str = _normalize_ws(type_str)
    if "&" not in type_str and "*" not in type_str:
        type_str = re.sub(r"^const\s+", "", type_str)
        type_str = re.sub(r"\s+const$", "", type_str)
    return type_str


def _param_types(param_str: str) -> List[str]:
    """Extract a normalized list of parameter *types* from a parameter list,
    discarding parameter names, doc comments and default values."""
    types: List[str] = []
    for raw in _split_top_level(param_str, ","):
        param = _strip_param_comment(raw).split("=")[0].strip()
        if not param:
            continue
        # The parameter name is the trailing identifier; remove it to keep the
        # type only. Unnamed parameters keep their full text.
        match = re.match(r"^(.*?)(\b[A-Za-z_]\w*)\s*$", param, re.DOTALL)
        if match and match.group(1).strip():
            param = match.group(1)
        types.append(_normalize_param_type(param))
    return types


def _leading_comment_start(text: str, sig_start: int) -> int:
    """Walk backwards from ``sig_start`` over contiguous comment lines (with no
    intervening blank line) and return the offset where the comment block
    begins."""
    start = sig_start
    while start > 0:
        prev_line_start = _line_start(text, start - 1)
        line = text[prev_line_start : start - 1] if start > 0 else ""
        stripped = line.strip()
        if stripped.startswith("//"):
            start = prev_line_start
        else:
            break
    return start


# ---------------------------------------------------------------------------
# Section parsing
# ---------------------------------------------------------------------------


@dataclass
class Section:
    title: str
    banner_start: int  # offset of the first banner rule line
    body_start: int  # offset just past the banner (third rule line + newline)
    body_end: int  # offset of the next banner, or end of region


def _find_sections(text: str) -> List[Section]:
    """Find all banner sections in ``text`` as character-offset spans."""
    lines = text.split("\n")
    # Precompute the start offset of each line.
    offsets: List[int] = []
    acc = 0
    for line in lines:
        offsets.append(acc)
        acc += len(line) + 1  # +1 for the '\n' we split on

    raw: List[Tuple[str, int, int]] = []  # (title, banner_start, body_start)
    i = 0
    while i + 2 < len(lines):
        if (
            _BANNER_RULE_RE.match(lines[i])
            and _BANNER_RULE_RE.match(lines[i + 2])
            and lines[i + 1].strip().startswith("//")
            and not _BANNER_RULE_RE.match(lines[i + 1])
        ):
            title = lines[i + 1].strip()[2:].strip()
            banner_start = offsets[i]
            body_start = offsets[i + 3] if i + 3 < len(lines) else len(text)
            raw.append((title, banner_start, body_start))
            i += 3
        else:
            i += 1

    sections: List[Section] = []
    for idx, (title, banner_start, body_start) in enumerate(raw):
        body_end = raw[idx + 1][1] if idx + 1 < len(raw) else len(text)
        sections.append(Section(title, banner_start, body_start, body_end))
    return sections


def _section_for_offset(sections: List[Section], offset: int) -> str:
    title = ""
    for section in sections:
        if section.body_start <= offset < section.body_end:
            title = section.title
    return title


# ---------------------------------------------------------------------------
# C++ definition (.cpp) parsing
# ---------------------------------------------------------------------------


def parse_cpp_functions(text: str, class_name: str) -> List[Function]:
    """Parse all ``<ReturnType> <ClassName> ::<name>(...) { ... }`` definitions."""
    sections = _find_sections(text)
    sig_re = re.compile(
        r"\b" + re.escape(class_name) + r"\s*::\s*(~?[A-Za-z_]\w*)\s*\("
    )
    functions: List[Function] = []
    for match in sig_re.finditer(text):
        name = match.group(1)
        paren_open = text.index("(", match.end() - 1)
        paren_close = _match_delimiter(text, paren_open, "(", ")")
        if paren_close == -1:
            continue
        brace_open = text.find("{", paren_close)
        if brace_open == -1:
            continue
        # Guard against matching declarations (which end in ';' before any '{').
        semi = text.find(";", paren_close)
        if semi != -1 and semi < brace_open:
            continue
        brace_close = _match_delimiter(text, brace_open, "{", "}")
        if brace_close == -1:
            continue
        sig_start = _line_start(text, match.start())
        block_start = _leading_comment_start(text, sig_start)
        block_end = brace_close + 1
        param_types = _param_types(text[paren_open + 1 : paren_close])
        section = _section_for_offset(sections, match.start())
        functions.append(
            Function(
                name=name,
                text=text[block_start:block_end],
                param_types=param_types,
                section=section,
                start=block_start,
                end=block_end,
            )
        )
    return functions


# ---------------------------------------------------------------------------
# C++ declaration (.hpp) parsing
# ---------------------------------------------------------------------------


def _class_body_span(text: str, class_name: str) -> Optional[Tuple[int, int]]:
    """Return ``(open_brace_idx, close_brace_idx)`` of the class body."""
    match = re.search(r"\bclass\s+" + re.escape(class_name) + r"\b", text)
    if not match:
        return None
    brace_open = text.find("{", match.end())
    if brace_open == -1:
        return None
    brace_close = _match_delimiter(text, brace_open, "{", "}")
    if brace_close == -1:
        return None
    return brace_open, brace_close


def parse_hpp_functions(text: str, class_name: str) -> List[Function]:
    """Parse member function declarations inside the class body."""
    span = _class_body_span(text, class_name)
    if span is None:
        return []
    body_open, body_close = span
    sections = _find_sections(text)

    functions: List[Function] = []
    i = body_open + 1
    stmt_start = i
    n = body_close
    while i < n:
        c = text[i]
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            nl = text.find("\n", i)
            i = n if nl == -1 else nl
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        if c in ('"', "'"):
            i = _skip_string(text, i)
            continue
        if c in "({[":
            i = _match_delimiter(text, i, c, {"(": ")", "{": "}", "[": "]"}[c])
            if i == -1:
                break
            i += 1
            continue
        if c == ";":
            func = _parse_hpp_statement(text, stmt_start, i + 1, sections)
            if func is not None:
                functions.append(func)
            stmt_start = i + 1
            i += 1
            continue
        if c == ":" and re.match(
            r"^[ \t]*(public|private|protected)\s*:",
            text[_line_start(text, i) : i + 1],
        ):
            # Access specifier resets the current statement.
            stmt_start = i + 1
        i += 1
    return functions


def _parse_hpp_statement(
    text: str, start: int, end: int, sections: List[Section]
) -> Optional[Function]:
    """Turn a ``;``-terminated statement into a :class:`Function`, or ``None``
    if it is not a function declaration."""
    # Locate the first '(' at depth 0 within the statement, skipping comments
    # and string literals, then take the identifier immediately before it.
    paren_open = _find_signature_paren(text, start, end)
    if paren_open is None:
        return None
    prefix = text[start:paren_open]
    # A nested type definition (class/struct/enum/union) or any brace before the
    # signature means this is not a top-level member function declaration.
    # Comments are stripped first so prose like "//! The Mode class" is ignored.
    code_prefix = _strip_comments(prefix)
    if "{" in code_prefix or re.search(
        r"\b(class|struct|enum|union|typedef|using|namespace)\b", code_prefix
    ):
        return None
    # Match against the original prefix (not the comment-stripped copy) so the
    # identifier offset is valid in ``text``; the name sits right before '(' so
    # no comment can appear between it and the parenthesis.
    ident_match = re.search(r"(~?[A-Za-z_]\w*)\s*$", prefix)
    if not ident_match:
        return None
    name = ident_match.group(1)
    if name in ("if", "for", "while", "switch", "return"):
        return None
    paren_close = _match_delimiter(text, paren_open, "(", ")")
    if paren_close == -1 or paren_close >= end:
        return None
    param_types = _param_types(text[paren_open + 1 : paren_close])
    sig_code_start = start + ident_match.start()
    block_start = _leading_comment_start(text, _line_start(text, sig_code_start))
    section = _section_for_offset(sections, paren_open)
    return Function(
        name=name,
        text=text[block_start:end],
        param_types=param_types,
        section=section,
        start=block_start,
        end=end,
    )


def _strip_comments(text: str) -> str:
    """Remove ``//`` line comments and ``/* */`` block comments from a snippet."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def _find_signature_paren(text: str, start: int, end: int) -> Optional[int]:
    """Return the offset of the first ``(`` in ``text[start:end]`` that is not
    inside a comment or string literal."""
    i = start
    while i < end:
        c = text[i]
        if c == "/" and i + 1 < end and text[i + 1] == "/":
            nl = text.find("\n", i)
            i = end if nl == -1 else nl
            continue
        if c == "/" and i + 1 < end and text[i + 1] == "*":
            close = text.find("*/", i + 2)
            i = end if close == -1 else close + 2
            continue
        if c in ('"', "'"):
            i = _skip_string(text, i)
            continue
        if c == "(":
            return i
        i += 1
    return None


# ---------------------------------------------------------------------------
# Include parsing
# ---------------------------------------------------------------------------


def _include_lines(text: str) -> List[str]:
    return [_normalize_ws(m.group(0)) for m in _INCLUDE_RE.finditer(text)]


def _last_include_end(text: str) -> Optional[int]:
    last = None
    for match in _INCLUDE_RE.finditer(text):
        last = match.end()
    return last


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------


def _access_by_section(template_hpp: str) -> Dict[str, str]:
    """Map each section title to the access specifier in effect for it."""
    mapping: Dict[str, str] = {}
    for section in _find_sections(template_hpp):
        prefix = template_hpp[: section.banner_start]
        access_tags = list(re.finditer(r"\b(public|private|protected)\s*:", prefix))
        mapping[section.title] = access_tags[-1].group(1) if access_tags else "public"
    return mapping


@dataclass
class _Insertion:
    offset: int
    text: str


def _collapse_blank_lines(text: str) -> str:
    """Collapse runs of 3 or more consecutive newlines down to 2 (a single
    blank line) so insertions do not leave large vertical gaps."""
    return re.sub(r"\n{3,}", "\n\n", text)


def _merge(
    template_text: str,
    user_text: str,
    class_name: str,
    is_header: bool,
) -> MergeResult:
    if is_header:
        template_funcs = parse_hpp_functions(template_text, class_name)
        user_funcs = parse_hpp_functions(user_text, class_name)
    else:
        template_funcs = parse_cpp_functions(template_text, class_name)
        user_funcs = parse_cpp_functions(user_text, class_name)

    user_by_name = {f.name: f for f in user_funcs}

    # Signature-drift detection for functions present in both.
    drifted: List[str] = []
    for func in template_funcs:
        existing = user_by_name.get(func.name)
        if existing is not None and existing.param_types != func.param_types:
            drifted.append(func.name)

    new_funcs = [f for f in template_funcs if f.name not in user_by_name]

    insertions: List[_Insertion] = []
    added: List[str] = []

    user_sections = {s.title: s for s in _find_sections(user_text)}
    access_map = _access_by_section(template_text) if is_header else {}

    # Group new functions by section, preserving template order.
    grouped: Dict[str, List[Function]] = {}
    section_order: List[str] = []
    for func in new_funcs:
        if func.section not in grouped:
            grouped[func.section] = []
            section_order.append(func.section)
        grouped[func.section].append(func)

    for title in section_order:
        funcs = grouped[title]
        added.extend(f.name for f in funcs)
        section = user_sections.get(title)
        if section is not None:
            offset, sep = _existing_section_insert_point(user_text, section, user_funcs)
            block = sep + "\n\n".join(f.text.strip("\n") for f in funcs) + "\n"
            insertions.append(_Insertion(offset, block))
        else:
            insertions.append(
                _new_section_insertion(
                    user_text,
                    user_funcs,
                    class_name,
                    title,
                    funcs,
                    is_header,
                    access_map.get(title, "private"),
                )
            )

    # Merge includes.
    added_includes: List[str] = []
    existing_includes = set(_include_lines(user_text))
    new_includes = [
        inc for inc in _include_lines(template_text) if inc not in existing_includes
    ]
    if new_includes:
        anchor = _last_include_end(user_text)
        if anchor is not None:
            added_includes = new_includes
            insertions.append(_Insertion(anchor, "\n" + "\n".join(new_includes)))

    if not insertions:
        return MergeResult(None, added, drifted, added_includes)

    # Apply insertions from last to first so offsets remain valid.
    insertions.sort(key=lambda ins: ins.offset, reverse=True)
    result = user_text
    for ins in insertions:
        result = result[: ins.offset] + ins.text + result[ins.offset :]

    return MergeResult(_collapse_blank_lines(result), added, drifted, added_includes)


def _existing_section_insert_point(
    user_text: str, section: Section, user_funcs: List[Function]
) -> Tuple[int, str]:
    """Return the offset and separator string for inserting at the end of an
    existing section in the user file."""
    last_end = None
    for func in user_funcs:
        if section.body_start <= func.start < section.body_end:
            if last_end is None or func.end > last_end:
                last_end = func.end
    if last_end is not None:
        return last_end, "\n\n"
    # Empty section: insert right after the banner.
    return section.body_start, ""


def _new_section_insertion(
    user_text: str,
    user_funcs: List[Function],
    class_name: str,
    title: str,
    funcs: List[Function],
    is_header: bool,
    access: str,
) -> _Insertion:
    """Construct an insertion that creates a brand-new section."""
    indent = "    " if is_header else ""
    rule = indent + "// " + "-" * 70
    banner = "\n".join([rule, indent + "// " + title, rule])
    body = "\n\n".join(f.text.strip("\n") for f in funcs)
    block = "\n" + banner + "\n\n" + body + "\n"

    if is_header:
        return _new_hpp_section_insertion(user_text, class_name, access, block)

    # .cpp: a brand-new section goes at the very end of the implementation,
    # i.e. just before the closing namespace brace if present, else at end of
    # the last function definition / file. Using the namespace close (rather
    # than the last function offset) keeps it after any insertions made into
    # pre-existing sections.
    ns_close = _namespace_close_offset(user_text)
    if ns_close is not None:
        return _Insertion(ns_close, block + "\n")
    if user_funcs:
        offset = max(f.end for f in user_funcs)
        return _Insertion(offset, "\n" + block)
    return _Insertion(len(user_text), "\n" + block)


def _new_hpp_section_insertion(
    user_text: str, class_name: str, access: str, block: str
) -> _Insertion:
    span = _class_body_span(user_text, class_name)
    if span is None:
        return _Insertion(len(user_text), block)
    body_open, body_close = span
    # Find the access region matching ``access``; insert at its end (just before
    # the next access tag or the class close).
    access_iter = list(
        re.finditer(
            r"^[ \t]*(public|private|protected)\s*:[ \t]*$",
            user_text[body_open:body_close],
            re.MULTILINE,
        )
    )
    regions: List[Tuple[str, int, int]] = []
    for idx, match in enumerate(access_iter):
        start = body_open + match.end()
        end = (
            body_open + access_iter[idx + 1].start()
            if idx + 1 < len(access_iter)
            else body_close
        )
        regions.append((match.group(1), start, end))

    for kind, _start, end in regions:
        if kind == access:
            return _Insertion(end, block + "\n")

    # No matching access region: add the access tag plus the section before the
    # class close.
    return _Insertion(body_close, "\n  " + access + ":\n" + block + "\n")


def _namespace_close_offset(text: str) -> Optional[int]:
    match = re.search(r"\bnamespace\s+\w+\s*\{", text)
    if not match:
        return None
    brace_open = text.index("{", match.start())
    brace_close = _match_delimiter(text, brace_open, "{", "}")
    return brace_close if brace_close != -1 else None


def merge_cpp(template_text: str, user_text: str, class_name: str) -> MergeResult:
    """Merge new definitions from ``template_text`` into ``user_text`` (.cpp)."""
    return _merge(template_text, user_text, class_name, is_header=False)


def merge_hpp(
    template_text: str,
    user_text: str,
    class_name: str,
) -> MergeResult:
    """Merge new declarations from ``template_text`` into ``user_text`` (.hpp)."""
    return _merge(template_text, user_text, class_name, is_header=True)

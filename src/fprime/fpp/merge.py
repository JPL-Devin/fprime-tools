"""fprime.fpp.merge: auto-merge of freshly generated impl templates with hand code

Provides ``fprime-util impl --auto-merge``. The implementation is intentionally
self-contained and is only invoked from ``impl.py`` so that normal implementation
generation stays untouched.

Strategy:
  * ``impl --auto-merge`` runs annotate the generated ``*.template.{hpp,cpp}``
    files with per-section "end" markers. For HPP sections the marker also stores
    a hash of the section contents, used to detect hand edits before a later merge.
  * With ``--auto-merge`` and pre-existing hand files, HPP sections are replaced
    only when their stored hash still matches (otherwise: warn and abort), while
    CPP sections are merged additively: new function stubs are appended, existing
    bodies are never modified or removed.

The guiding rule is "never delete hand-written code": anything ambiguous results
in a warning and an aborted merge rather than a risky edit.

@author Devin
"""

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from fprime.common.error import FprimeException

# A line of dashes inside a comment, e.g. "    // ----------------------------"
DASH_RE = re.compile(r"^\s*//\s*-{5,}\s*$")
# End-of-section marker injected by this module (hash group is HPP-only).
END_RE = re.compile(
    r"^(?P<indent>\s*)//\s*fprime-util auto-merge: end of section "
    r'"(?P<title>.*?)"(?:;\s*section-hash=(?P<hash>[0-9a-fA-F]+))?'
)
# A trailing access specifier such as "  private:" living between two sections.
ACCESS_RE = re.compile(r"^\s*(public|private|protected)\s*:\s*$")
# Closing brace of the component class in an HPP file.
CLASS_CLOSE_RE = re.compile(r"^\s*};\s*$")
# A namespace-closing brace: a lone "}" (optionally with a trailing comment), no
# semicolon (which would make it a struct/enum close instead).
NAMESPACE_CLOSE_RE = re.compile(r"^\s*\}\s*(?://.*)?$")
# A namespace-opening line such as "namespace Svc {".
NAMESPACE_OPEN_RE = re.compile(r"^\s*namespace\s+\w+\s*\{\s*(?://.*)?$")
# An identifier immediately followed by "(": a declaration/definition name.
DECL_NAME_RE = re.compile(r"(~?[A-Za-z_]\w*)\s*\(")

HASH_LENGTH = 16


class ImplMergeError(FprimeException):
    """Raised to abort an auto-merge; callers turn this into a warning."""


@dataclass
class Section:
    """A single banner-delimited section of an impl file."""

    indent: str
    title: str
    body_lines: List[str]
    stored_hash: Optional[str] = None
    gap_lines: List[str] = field(default_factory=list)


@dataclass
class ParsedImpl:
    """An impl file split into preamble, sections and trailer."""

    preamble_lines: List[str]
    sections: List[Section]
    trailer_lines: List[str]


@dataclass
class FunctionBlock:
    """A C++ member function definition extracted from a CPP section."""

    name: str
    lines: List[str]


def _canonicalize(lines: List[str]) -> str:
    """Normalize section text so cosmetic whitespace does not change the hash."""
    stripped = [line.rstrip() for line in lines]
    collapsed: List[str] = []
    for line in stripped:
        if not line and collapsed and not collapsed[-1]:
            continue  # collapse consecutive blank lines
        collapsed.append(line)
    while collapsed and not collapsed[0]:
        collapsed.pop(0)
    while collapsed and not collapsed[-1]:
        collapsed.pop()
    return "\n".join(collapsed)


def section_hash(body_lines: List[str]) -> str:
    """Return a stable short hash of a section body."""
    digest = hashlib.sha256(_canonicalize(body_lines).encode("utf-8"))
    return digest.hexdigest()[:HASH_LENGTH]


def _trim_edges(lines: List[str]) -> List[str]:
    """Drop leading and trailing blank lines."""
    result = list(lines)
    while result and not result[0].strip():
        result.pop(0)
    while result and not result[-1].strip():
        result.pop()
    return result


def _is_title_line(line: str) -> bool:
    """A banner title line is a comment that is neither dashes nor empty."""
    if DASH_RE.match(line):
        return False
    match = re.match(r"^\s*//\s?(?P<title>.*\S)\s*$", line)
    return match is not None


def _parse_title(line: str) -> Tuple[str, str]:
    """Return (indent, title) for a banner title line."""
    match = re.match(r"^(?P<indent>\s*)//\s?(?P<title>.*\S)\s*$", line)
    if match is None:
        raise ImplMergeError(f"unrecognized banner title line: {line!r}")
    return match.group("indent"), match.group("title")


def _find_banner_starts(lines: List[str], limit: int) -> List[int]:
    """Indices of the first dash line of every 3-line section banner before limit."""
    starts = []
    index = 0
    while index < limit - 2:
        if (
            DASH_RE.match(lines[index])
            and _is_title_line(lines[index + 1])
            and DASH_RE.match(lines[index + 2])
        ):
            starts.append(index)
            index += 3
        else:
            index += 1
    return starts


def _namespace_close_lines(lines: List[str]) -> List[bool]:
    """Per line: whether its (only) closing brace pops a ``namespace X {`` brace.

    Braces inside comments and string/char literals are ignored. A line is
    flagged only when the single brace it closes was opened by a line matching
    ``NAMESPACE_OPEN_RE``.
    """
    flags = [False] * len(lines)
    stack: List[bool] = []  # True where the open brace came from a namespace line
    state = "normal"
    for line_no, line in enumerate(lines):
        is_ns_open = state == "normal" and NAMESPACE_OPEN_RE.match(line) is not None
        index = 0
        length = len(line)
        while index < length:
            char = line[index]
            nxt = line[index + 1] if index + 1 < length else ""
            if state == "block_comment":
                if char == "*" and nxt == "/":
                    state = "normal"
                    index += 1
            elif state == "string":
                if char == "\\":
                    index += 1
                elif char == '"':
                    state = "normal"
            elif state == "char":
                if char == "\\":
                    index += 1
                elif char == "'":
                    state = "normal"
            else:
                if char == "/" and nxt == "/":
                    break
                if char == "/" and nxt == "*":
                    state = "block_comment"
                    index += 1
                elif char == '"':
                    state = "string"
                elif char == "'":
                    state = "char"
                elif char == "{":
                    stack.append(is_ns_open)
                elif char == "}":
                    flags[line_no] = bool(stack) and stack.pop()
            index += 1
    return flags


def parse_impl(
    text: str, trailer_re: Optional["re.Pattern[str]"] = CLASS_CLOSE_RE
) -> ParsedImpl:
    """Parse an impl file into preamble, banner-delimited sections and trailer.

    ``trailer_re`` matches the first trailer line: the class-closing ``};`` for
    HPP files (``CLASS_CLOSE_RE``) or the namespace-closing ``}`` for CPP files
    (``NAMESPACE_CLOSE_RE``). ``None`` disables trailer detection. Keeping the
    namespace close in the trailer ensures appended CPP stubs land inside it.
    """
    lines = text.split("\n")

    # The closing brace and everything after it is the trailer. For CPP files,
    # every namespace opened must close in the trailer (nested namespaces).
    trailer_start = len(lines)
    if trailer_re is not None:
        for index in range(len(lines) - 1, -1, -1):
            if trailer_re.match(lines[index]):
                trailer_start = index
                break
        if trailer_re is NAMESPACE_CLOSE_RE and trailer_start < len(lines):
            # Extend the trailer backward over blank lines and closing braces
            # that verifiably pop a namespace-opened brace (nested namespaces).
            ns_close = _namespace_close_lines(lines)
            if not ns_close[trailer_start]:
                raise ImplMergeError(
                    "unbalanced braces near the namespace-closing trailer"
                )
            probe = trailer_start - 1
            while probe >= 0:
                if not lines[probe].strip():
                    probe -= 1
                    continue
                if trailer_re.match(lines[probe]) and ns_close[probe]:
                    trailer_start = probe
                    probe -= 1
                    continue
                break

    banner_starts = _find_banner_starts(lines, trailer_start)
    if not banner_starts:
        return ParsedImpl(lines[:trailer_start], [], lines[trailer_start:])

    preamble = lines[: banner_starts[0]]
    sections: List[Section] = []
    for position, start in enumerate(banner_starts):
        indent, title = _parse_title(lines[start + 1])
        region_end = (
            banner_starts[position + 1]
            if position + 1 < len(banner_starts)
            else trailer_start
        )
        region = lines[start + 3 : region_end]
        body_lines, gap_lines, stored_hash = _split_region(region, title)
        sections.append(
            Section(
                indent=indent,
                title=title,
                body_lines=body_lines,
                stored_hash=stored_hash,
                gap_lines=gap_lines,
            )
        )
    return ParsedImpl(preamble, sections, lines[trailer_start:])


def _split_region(
    region: List[str], title: str
) -> Tuple[List[str], List[str], Optional[str]]:
    """Split a section region into (body, gap, stored_hash).

    The gap is the inter-section text (access specifiers, blank lines) that sits
    between a section and the next banner. If an end marker is present it bounds
    the body authoritatively; otherwise trailing gap lines are inferred.
    """
    for offset, line in enumerate(region):
        match = END_RE.match(line)
        if match and match.group("title") == title:
            body = region[:offset]
            gap = [line for line in region[offset + 1 :] if line.strip()]
            return _trim_edges(body), gap, match.group("hash")

    # No marker yet: peel trailing access-specifier / blank lines into the gap.
    cut = len(region)
    while cut > 0 and (not region[cut - 1].strip() or ACCESS_RE.match(region[cut - 1])):
        cut -= 1
    body = region[:cut]
    gap = [line for line in region[cut:] if line.strip()]
    return _trim_edges(body), gap, None


def _banner(indent: str, title: str) -> List[str]:
    dashes = f"{indent}// " + "-" * 70
    return [dashes, f"{indent}// {title}", dashes]


def _end_marker(indent: str, title: str, hashed: Optional[str]) -> str:
    base = f'{indent}// fprime-util auto-merge: end of section "{title}"'
    if hashed is None:
        return base
    return f"{base}; section-hash={hashed} (detects manual edits before re-merge)"


def render_impl(parsed: ParsedImpl) -> str:
    """Render a parsed impl (with refreshed markers) back to text."""
    out: List[str] = _trim_edges(parsed.preamble_lines)
    for section in parsed.sections:
        out.append("")
        out.extend(_banner(section.indent, section.title))
        out.append("")
        out.extend(_trim_edges(section.body_lines))
        out.append("")
        out.append(_end_marker(section.indent, section.title, section.stored_hash))
        if section.gap_lines:
            out.append("")
            out.extend(section.gap_lines)
    out.append("")
    out.extend(parsed.trailer_lines)
    text = "\n".join(out)
    return text if text.endswith("\n") else text + "\n"


def annotate_file(path: Path, with_hash: bool) -> None:
    """Inject (or refresh) section end markers in a generated template file."""
    parsed = parse_impl(
        path.read_text(encoding="utf-8"),
        trailer_re=CLASS_CLOSE_RE if path.suffix == ".hpp" else NAMESPACE_CLOSE_RE,
    )
    if not parsed.sections:
        return
    for section in parsed.sections:
        section.stored_hash = section_hash(section.body_lines) if with_hash else None
    path.write_text(render_impl(parsed), encoding="utf-8")


def split_functions(body_lines: List[str]) -> List[FunctionBlock]:
    """Extract member-function definitions from a CPP section body.

    Definitions are detected by brace matching while ignoring braces inside
    comments, strings and character literals. The function name is the identifier
    (optionally prefixed with ``~`` for destructors) preceding the parameter list.
    """
    text = "\n".join(body_lines)
    blocks: List[FunctionBlock] = []
    index = 0
    length = len(text)
    seg_start: Optional[int] = None
    depth = 0
    state = "normal"
    while index < length:
        char = text[index]
        nxt = text[index + 1] if index + 1 < length else ""
        if state == "line_comment":
            if char == "\n":
                state = "normal"
        elif state == "block_comment":
            if char == "*" and nxt == "/":
                state = "normal"
                index += 2
                continue
        elif state == "string":
            if char == "\\":
                index += 2
                continue
            if char == '"':
                state = "normal"
        elif state == "char":
            if char == "\\":
                index += 2
                continue
            if char == "'":
                state = "normal"
        else:
            if char == "/" and nxt == "/":
                state = "line_comment"
            elif char == "/" and nxt == "*":
                state = "block_comment"
            elif char == '"':
                state = "string"
            elif char == "'":
                state = "char"
            elif char == "{":
                if seg_start is None:
                    seg_start = index
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0 and seg_start is not None:
                    block_text = text[seg_start : index + 1]
                    blocks.append(
                        FunctionBlock(
                            name=_function_name(block_text),
                            lines=block_text.split("\n"),
                        )
                    )
                    seg_start = None
            elif not char.isspace() and seg_start is None:
                seg_start = index
        index += 1
    return blocks


def _function_name(block_text: str) -> str:
    """Return the name of the function defined by a CPP block."""
    brace = block_text.find("{")
    signature = block_text[:brace] if brace != -1 else block_text
    paren = signature.find("(")
    if paren == -1:
        first_line = block_text.split("\n", 1)[0].strip()
        raise ImplMergeError(
            f"unable to parse a CPP function definition (near {first_line!r})"
        )
    match = re.search(r"(~?\w+)\s*$", signature[:paren])
    if match is None:
        raise ImplMergeError("unable to determine a CPP function name")
    return match.group(1)


def _function_map(blocks: List[FunctionBlock], where: str) -> Dict[str, FunctionBlock]:
    """Map function name to block, aborting on duplicate (e.g. overloaded) names."""
    mapping: Dict[str, FunctionBlock] = {}
    for block in blocks:
        if block.name in mapping:
            raise ImplMergeError(
                f"duplicate function name '{block.name}' in {where}; "
                "auto merge cannot disambiguate overloads"
            )
        mapping[block.name] = block
    return mapping


def _sections_by_title(sections: List[Section], where: str) -> Dict[str, Section]:
    """Map section title to section, aborting on duplicate banner titles."""
    mapping: Dict[str, Section] = {}
    for section in sections:
        if section.title in mapping:
            raise ImplMergeError(
                f'duplicate section title "{section.title}" in {where}; '
                "auto merge cannot disambiguate"
            )
        mapping[section.title] = section
    return mapping


def _preserve_removed_sections(
    existing: ParsedImpl,
    template_titles: set,
    merged: List[Section],
    warnings: List[str],
) -> None:
    """Append existing sections absent from the template, warning for each."""
    for section in existing.sections:
        if section.title not in template_titles:
            warnings.append(
                f'section "{section.title}" is no longer in the model; preserved as-is'
            )
            merged.append(section)


def merge_hpp(existing_text: str, template_text: str) -> Tuple[str, List[str]]:
    """Merge an HPP template into the existing HPP, returning (text, warnings)."""
    existing = parse_impl(existing_text)
    template = parse_impl(template_text)
    warnings: List[str] = []

    if not existing.sections:
        raise ImplMergeError(
            "existing HPP has no recognizable sections "
            "(file predates auto-merge); not attempting auto merge"
        )

    for section in existing.sections:
        if section.stored_hash is None:
            raise ImplMergeError(
                f'section "{section.title}" has no auto-merge marker '
                "(file predates auto-merge); not attempting auto merge"
            )
        if section_hash(section.body_lines) != section.stored_hash:
            raise ImplMergeError(
                f'section "{section.title}" has changed, not attempting auto merge'
            )

    existing_by_title = _sections_by_title(existing.sections, "existing HPP")
    _sections_by_title(template.sections, "template HPP")
    template_titles = {section.title for section in template.sections}

    merged: List[Section] = []
    for tmpl in template.sections:
        prior = existing_by_title.get(tmpl.title)
        gap = prior.gap_lines if prior is not None else tmpl.gap_lines
        merged.append(
            Section(
                indent=prior.indent if prior is not None else tmpl.indent,
                title=tmpl.title,
                body_lines=tmpl.body_lines,
                stored_hash=section_hash(tmpl.body_lines),
                gap_lines=gap,
            )
        )
    _preserve_removed_sections(existing, template_titles, merged, warnings)

    result = ParsedImpl(existing.preamble_lines, merged, existing.trailer_lines)
    return render_impl(result), warnings


def _orphaned_definition_warnings(merged_hpp: str, merged_cpp: str) -> List[str]:
    """Warn about class-member definitions absent from the merged HPP declarations.

    Catches members orphaned by a model change (their declaration was regenerated
    away while the definition was kept, per never-delete) which would otherwise
    fail to compile silently. Only class-qualified (``Class ::``) definitions are
    considered, so file-local helpers and hand helpers declared in the header are
    never flagged.
    """
    declared = {match.group(1) for match in DECL_NAME_RE.finditer(merged_hpp)}
    parsed = parse_impl(merged_cpp, trailer_re=NAMESPACE_CLOSE_RE)
    warnings: List[str] = []
    seen: set = set()
    for section in parsed.sections:
        try:
            blocks = split_functions(section.body_lines)
        except ImplMergeError:
            # Unparseable sections are skipped: this is a warning-only pass.
            continue
        for block in blocks:
            signature = "\n".join(block.lines)
            head = signature.split("(", 1)[0]
            if "::" not in head:
                continue
            if block.name in declared or block.name in seen:
                continue
            seen.add(block.name)
            warnings.append(
                f"{block.name} is defined in the .cpp but no longer declared in the "
                ".hpp (model removed it?); kept to avoid deleting hand code - remove "
                "it manually or restore the model"
            )
    return warnings


def perform_auto_merge(
    template_hpp: Path,
    template_cpp: Path,
    target_hpp: Path,
    target_cpp: Path,
) -> bool:
    """Auto-merge one component's templates into its hand files.

    All merged text is computed in memory before any target file is touched, then
    committed via temporary files. On a merge abort the targets and templates are
    left untouched and ``False`` is returned; a mid-commit I/O failure may leave
    the pair partially updated (reported in the warning). Templates are removed
    only on success.
    """
    if not target_hpp.exists() and not target_cpp.exists():
        template_hpp.rename(target_hpp)
        template_cpp.rename(target_cpp)
        print(
            f"[INFO] No existing implementation found; created {target_hpp.name} "
            f"and {target_cpp.name} from templates."
        )
        return True
    if not target_hpp.exists() or not target_cpp.exists():
        print(
            f"[WARNING] Only one of {target_hpp.name} / {target_cpp.name} exists; "
            "not attempting auto merge."
        )
        return False

    try:
        merged_hpp, hpp_warnings = merge_hpp(
            target_hpp.read_text(encoding="utf-8"),
            template_hpp.read_text(encoding="utf-8"),
        )
        merged_cpp, cpp_warnings = merge_cpp(
            target_cpp.read_text(encoding="utf-8"),
            template_cpp.read_text(encoding="utf-8"),
        )
    except ImplMergeError as error:
        print(f"[WARNING] {error}. Auto merge aborted; templates left in place.")
        return False
    except (OSError, UnicodeError) as error:
        print(f"[WARNING] auto merge I/O failure: {error}. Templates left in place.")
        return False

    # Unique temp names so a leftover or user file at a fixed name is never
    # clobbered or deleted.
    handle_hpp, tmp_name_hpp = tempfile.mkstemp(
        dir=target_hpp.parent, prefix=target_hpp.name + ".automerge.", suffix=".tmp"
    )
    handle_cpp, tmp_name_cpp = tempfile.mkstemp(
        dir=target_cpp.parent, prefix=target_cpp.name + ".automerge.", suffix=".tmp"
    )
    os.close(handle_hpp)
    os.close(handle_cpp)
    tmp_hpp = Path(tmp_name_hpp)
    tmp_cpp = Path(tmp_name_cpp)
    committed: List[str] = []
    try:
        tmp_hpp.write_text(merged_hpp, encoding="utf-8")
        tmp_cpp.write_text(merged_cpp, encoding="utf-8")
        os.replace(tmp_hpp, target_hpp)
        committed.append(target_hpp.name)
        os.replace(tmp_cpp, target_cpp)
        committed.append(target_cpp.name)
    except OSError as error:
        print(
            f"[WARNING] auto merge I/O failure while committing: {error}. "
            f"Files updated so far: {', '.join(committed) or 'none'}. "
            "Templates left in place."
        )
        return False
    finally:
        for leftover in (tmp_hpp, tmp_cpp):
            if leftover.exists():
                leftover.unlink()

    template_hpp.unlink()
    template_cpp.unlink()
    orphan_warnings = _orphaned_definition_warnings(merged_hpp, merged_cpp)
    for warning in hpp_warnings + cpp_warnings + orphan_warnings:
        print(f"[WARNING] {warning}")
    print(f"[INFO] Auto-merged templates into {target_hpp.name} and {target_cpp.name}.")
    return True


def merge_cpp(existing_text: str, template_text: str) -> Tuple[str, List[str]]:
    """Merge a CPP template into the existing CPP additively, returning (text, warnings)."""
    existing = parse_impl(existing_text, trailer_re=NAMESPACE_CLOSE_RE)
    template = parse_impl(template_text, trailer_re=NAMESPACE_CLOSE_RE)
    warnings: List[str] = []

    if not existing.sections and template.sections:
        raise ImplMergeError(
            "existing CPP has no recognizable sections "
            "(file predates auto-merge); not attempting auto merge"
        )

    existing_by_title = _sections_by_title(existing.sections, "existing CPP")
    template_titles = {section.title for section in template.sections}

    merged: List[Section] = []
    for tmpl in template.sections:
        prior = existing_by_title.get(tmpl.title)
        if prior is None:
            merged.append(
                Section(
                    indent=tmpl.indent,
                    title=tmpl.title,
                    body_lines=tmpl.body_lines,
                    gap_lines=tmpl.gap_lines,
                )
            )
            continue
        code_in_gap = [
            line
            for line in prior.gap_lines
            if line.strip() and not line.strip().startswith("//")
        ]
        if code_in_gap:
            raise ImplMergeError(
                f'code found after the end marker of section "{tmpl.title}" '
                "(move it above the marker); not attempting auto merge"
            )
        existing_funcs = _function_map(
            split_functions(prior.body_lines), f'existing section "{tmpl.title}"'
        )
        template_funcs = split_functions(tmpl.body_lines)
        # Called solely to raise on duplicate (overloaded) template names.
        _function_map(template_funcs, f'template section "{tmpl.title}"')

        body = _trim_edges(prior.body_lines)
        appended = [
            block for block in template_funcs if block.name not in existing_funcs
        ]
        for block in appended:
            body.append("")
            body.extend(_trim_edges(block.lines))
        if appended:
            warnings.append(
                f'section "{tmpl.title}": added {len(appended)} new function stub(s): '
                + ", ".join(block.name for block in appended)
            )
        merged.append(
            Section(
                indent=prior.indent,
                title=tmpl.title,
                body_lines=body,
                gap_lines=prior.gap_lines,
            )
        )
    _preserve_removed_sections(existing, template_titles, merged, warnings)

    result = ParsedImpl(existing.preamble_lines, merged, existing.trailer_lines)
    return render_impl(result), warnings

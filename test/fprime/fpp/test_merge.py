"""
Tests for fprime.fpp.merge (impl template auto-merge).
"""

import textwrap

import pytest

from fprime.fpp import merge


def _banner(title, indent=""):
    dashes = f"{indent}// " + "-" * 70
    return f"{dashes}\n{indent}// {title}\n{dashes}"


DASHES = "-" * 70
INDENT_DASHES = "    // " + DASHES
FLUSH_DASHES = "// " + DASHES

CTOR_TITLE = "Component construction and destruction"
HANDLER_TITLE = "Handler implementations for typed input ports"

HPP_TEMPLATE = (
    textwrap.dedent(
        """\
        // ======================================================================
        // \\title  Comp.hpp
        // \\author [user name]
        // ======================================================================

        #ifndef Comp_HPP
        #define Comp_HPP

        #include "CompComponentAc.hpp"

        class Comp final :
          public CompComponentBase
        {

          public:

        __CTOR_BANNER__

            //! Construct Comp object
            Comp(
                const char* const compName //!< The component name
            );

            //! Destroy Comp object
            ~Comp();

          private:

        __HANDLER_BANNER__

            //! Handler implementation for portOne
            void portOne_handler(
                FwIndexType portNum //!< The port number
            ) override;

            //! Handler implementation for portTwo
            void portTwo_handler(
                FwIndexType portNum //!< The port number
            ) override;

        };

        #endif
        """
    )
    .replace("__CTOR_BANNER__", _banner(CTOR_TITLE, "    "))
    .replace("__HANDLER_BANNER__", _banner(HANDLER_TITLE, "    "))
)


CPP_TEMPLATE = (
    textwrap.dedent(
        """\
        // ======================================================================
        // \\title  Comp.cpp
        // ======================================================================

        #include "Comp.hpp"

        namespace M {

        __CTOR_BANNER__

        Comp ::
          Comp(const char* const compName)
        {

        }

        Comp ::
          ~Comp()
        {

        }

        __HANDLER_BANNER__

        void Comp ::
          portOne_handler(FwIndexType portNum)
        {
          // TODO
        }

        void Comp ::
          portTwo_handler(FwIndexType portNum)
        {
          // TODO
        }

        }  // namespace M
        """
    )
    .replace("__CTOR_BANNER__", _banner(CTOR_TITLE))
    .replace("__HANDLER_BANNER__", _banner(HANDLER_TITLE))
)


def _annotated(text, with_hash):
    """Return the annotated form of an impl file (as impl generation would emit).

    HPP files (hashed) use the class-close trailer; CPP files use the
    namespace-close trailer, matching production annotation.
    """
    trailer_re = merge.CLASS_CLOSE_RE if with_hash else merge.NAMESPACE_CLOSE_RE
    parsed = merge.parse_impl(text, trailer_re=trailer_re)
    for section in parsed.sections:
        section.stored_hash = (
            merge.section_hash(section.body_lines) if with_hash else None
        )
    return merge.render_impl(parsed)


# --------------------------------------------------------------------------
# Parsing / hashing / annotation
# --------------------------------------------------------------------------
def test_parse_finds_sections_and_trailer():
    parsed = merge.parse_impl(HPP_TEMPLATE)
    titles = [section.title for section in parsed.sections]
    assert titles == [
        "Component construction and destruction",
        "Handler implementations for typed input ports",
    ]
    assert any("#endif" in line for line in parsed.trailer_lines)
    assert any("};" in line for line in parsed.trailer_lines)


def test_hash_is_whitespace_insensitive():
    base = ["    void foo();", "", "    void bar();"]
    noisy = ["    void foo();   ", "", "", "    void bar();", ""]
    assert merge.section_hash(base) == merge.section_hash(noisy)


def test_annotation_adds_markers_and_is_idempotent():
    annotated = _annotated(HPP_TEMPLATE, with_hash=True)
    assert 'end of section "Component construction and destruction"' in annotated
    assert "section-hash=" in annotated
    # Re-parsing then re-rendering must be stable.
    again = merge.render_impl(merge.parse_impl(annotated))
    assert again == annotated


def test_annotation_no_sections_is_noop(tmp_path):
    path = tmp_path / "plain.hpp"
    path.write_text("int main() { return 0; }\n")
    merge.annotate_file(path, with_hash=True)
    assert path.read_text() == "int main() { return 0; }\n"


# --------------------------------------------------------------------------
# Function extraction
# --------------------------------------------------------------------------
def test_split_functions_names_including_destructor():
    body = merge.parse_impl(CPP_TEMPLATE).sections
    ctor_section = body[0]
    names = [fn.name for fn in merge.split_functions(ctor_section.body_lines)]
    assert names == ["Comp", "~Comp"]


def test_split_functions_ignores_braces_in_strings_and_comments():
    snippet = [
        "void Comp ::",
        "  noisy()",
        "{",
        '  const char* s = "}{";  // } not real',
        "  /* } still not real */",
        "  if (true) { doThing(); }",
        "}",
    ]
    blocks = merge.split_functions(snippet)
    assert len(blocks) == 1
    assert blocks[0].name == "noisy"


def test_split_functions_tracks_depth_after_leading_brace_block():
    # A bare "{...}" block whose first non-whitespace char is "{" must still
    # increment brace depth; otherwise following functions are silently dropped.
    snippet = [
        "{",
        "  scoped();",
        "}",
        "",
        "void Comp ::",
        "  after()",
        "{",
        "  // TODO",
        "}",
    ]
    # The leading anonymous block has no signature, so we abort rather than
    # corrupt depth tracking and lose "after".
    with pytest.raises(merge.ImplMergeError):
        merge.split_functions(snippet)


def test_split_functions_finds_all_after_nested_blocks():
    snippet = [
        "void Comp ::",
        "  first()",
        "{",
        "  if (x) { a(); } else { b(); }",
        "}",
        "",
        "void Comp ::",
        "  second()",
        "{",
        "  while (y) { c(); }",
        "}",
    ]
    names = [block.name for block in merge.split_functions(snippet)]
    assert names == ["first", "second"]


def test_duplicate_function_names_abort():
    blocks = [merge.FunctionBlock("foo", []), merge.FunctionBlock("foo", [])]
    with pytest.raises(merge.ImplMergeError):
        merge._function_map(blocks, "test")


# --------------------------------------------------------------------------
# HPP merge
# --------------------------------------------------------------------------
def test_merge_hpp_unchanged_section_replaced_in_place():
    annotated = _annotated(HPP_TEMPLATE, with_hash=True)
    merged, warnings = merge.merge_hpp(annotated, annotated)
    assert warnings == []
    # Idempotent: re-rendered text matches.
    assert merge.render_impl(merge.parse_impl(merged)) == merged


def test_merge_hpp_aborts_on_hand_edit():
    existing = _annotated(HPP_TEMPLATE, with_hash=True)
    edited = existing.replace("~Comp();", "~Comp();\n    void helper();")
    with pytest.raises(merge.ImplMergeError, match="has changed"):
        merge.merge_hpp(edited, existing)


def test_merge_hpp_aborts_on_legacy_file_without_markers():
    legacy = HPP_TEMPLATE  # never annotated
    template = _annotated(HPP_TEMPLATE, with_hash=True)
    with pytest.raises(merge.ImplMergeError, match="no auto-merge marker"):
        merge.merge_hpp(legacy, template)


def test_merge_hpp_aborts_on_sectionless_file():
    template = _annotated(HPP_TEMPLATE, with_hash=True)
    with pytest.raises(merge.ImplMergeError, match="no recognizable sections"):
        merge.merge_hpp("class Comp {};\n", template)


def test_merge_hpp_preserves_removed_section():
    existing = _annotated(HPP_TEMPLATE, with_hash=True)
    # Build a template that no longer has the handler section.
    parsed = merge.parse_impl(HPP_TEMPLATE)
    parsed.sections = [s for s in parsed.sections if s.title != HANDLER_TITLE]
    smaller = _annotated(merge.render_impl(parsed), with_hash=True)
    merged, warnings = merge.merge_hpp(existing, smaller)
    assert "portOne_handler" in merged  # hand code preserved
    assert any("no longer in the model" in warning for warning in warnings)


# --------------------------------------------------------------------------
# CPP merge
# --------------------------------------------------------------------------
def test_merge_cpp_appends_new_function_and_preserves_bodies():
    template = _annotated(CPP_TEMPLATE, with_hash=False)
    # Existing lacks portTwo and has a hand-written portOne body.
    existing_src = CPP_TEMPLATE.replace(
        "void Comp ::\n  portTwo_handler(FwIndexType portNum)\n{\n  // TODO\n}\n",
        "",
    ).replace(
        "portOne_handler(FwIndexType portNum)\n{\n  // TODO\n}",
        "portOne_handler(FwIndexType portNum)\n{\n  this->hello();\n}",
    )
    existing = _annotated(existing_src, with_hash=False)
    merged, warnings = merge.merge_cpp(existing, template)
    assert "this->hello();" in merged  # hand body preserved
    assert "portTwo_handler" in merged  # new stub appended
    assert any("portTwo_handler" in warning for warning in warnings)


def test_merge_cpp_noop_when_nothing_new():
    template = _annotated(CPP_TEMPLATE, with_hash=False)
    merged, warnings = merge.merge_cpp(template, template)
    assert warnings == []


def test_merge_cpp_appends_inside_namespace():
    # A stub added to the LAST section must land before the namespace-closing
    # brace, not after it (which would not compile).
    template = _annotated(CPP_TEMPLATE, with_hash=False)
    existing = _annotated(
        CPP_TEMPLATE.replace(
            "void Comp ::\n  portTwo_handler(FwIndexType portNum)\n{\n  // TODO\n}\n",
            "",
        ),
        with_hash=False,
    )
    merged, _ = merge.merge_cpp(existing, template)
    new_index = merged.index("portTwo_handler")
    ns_index = merged.index("}  // namespace M")
    assert new_index < ns_index


def test_cpp_parse_not_truncated_by_struct_close_brace():
    # A hand struct ending in "};" inside an early section must not be mistaken
    # for a class-closing brace and truncate later sections.
    template = _annotated(CPP_TEMPLATE, with_hash=False)
    existing_src = _annotated(CPP_TEMPLATE, with_hash=False).replace(
        "  Comp(const char* const compName)\n{\n\n}",
        "  Comp(const char* const compName)\n{\n  struct Local { int x; };\n}",
    )
    existing = existing_src
    # portTwo removed from existing so the merge must append it to the *second*
    # section, which only survives if parsing was not truncated at "};".
    existing = existing.replace(
        "void Comp ::\n  portTwo_handler(FwIndexType portNum)\n{\n  // TODO\n}\n",
        "",
    )
    merged, warnings = merge.merge_cpp(existing, template)
    assert "portTwo_handler" in merged
    assert any("portTwo_handler" in warning for warning in warnings)


# --------------------------------------------------------------------------
# Orchestration (perform_auto_merge)
# --------------------------------------------------------------------------
def _write_templates(directory):
    thpp = directory / "Comp.template.hpp"
    tcpp = directory / "Comp.template.cpp"
    thpp.write_text(_annotated(HPP_TEMPLATE, with_hash=True))
    tcpp.write_text(_annotated(CPP_TEMPLATE, with_hash=False))
    return thpp, tcpp


def test_perform_auto_merge_promotes_when_no_existing(tmp_path):
    thpp, tcpp = _write_templates(tmp_path)
    ok = merge.perform_auto_merge(
        thpp, tcpp, tmp_path / "Comp.hpp", tmp_path / "Comp.cpp"
    )
    assert ok
    assert (tmp_path / "Comp.hpp").exists()
    assert not thpp.exists() and not tcpp.exists()


def test_perform_auto_merge_success_removes_templates(tmp_path):
    thpp, tcpp = _write_templates(tmp_path)
    (tmp_path / "Comp.hpp").write_text(_annotated(HPP_TEMPLATE, with_hash=True))
    (tmp_path / "Comp.cpp").write_text(_annotated(CPP_TEMPLATE, with_hash=False))
    ok = merge.perform_auto_merge(
        thpp, tcpp, tmp_path / "Comp.hpp", tmp_path / "Comp.cpp"
    )
    assert ok
    assert not thpp.exists() and not tcpp.exists()


def test_perform_auto_merge_aborts_and_keeps_templates_on_hand_edit(tmp_path):
    thpp, tcpp = _write_templates(tmp_path)
    hand_hpp = _annotated(HPP_TEMPLATE, with_hash=True).replace(
        "~Comp();", "~Comp();\n    void helper();"
    )
    target_hpp = tmp_path / "Comp.hpp"
    target_cpp = tmp_path / "Comp.cpp"
    target_hpp.write_text(hand_hpp)
    target_cpp.write_text(_annotated(CPP_TEMPLATE, with_hash=False))
    ok = merge.perform_auto_merge(thpp, tcpp, target_hpp, target_cpp)
    assert not ok
    assert thpp.exists() and tcpp.exists()  # templates kept for manual merge
    assert target_hpp.read_text() == hand_hpp  # untouched
    assert not (tmp_path / "Comp.hpp.automerge.tmp").exists()  # temp cleaned up


def test_perform_auto_merge_aborts_when_only_one_target_exists(tmp_path):
    thpp, tcpp = _write_templates(tmp_path)
    (tmp_path / "Comp.hpp").write_text(_annotated(HPP_TEMPLATE, with_hash=True))
    ok = merge.perform_auto_merge(
        thpp, tcpp, tmp_path / "Comp.hpp", tmp_path / "Comp.cpp"
    )
    assert not ok
    assert thpp.exists() and tcpp.exists()

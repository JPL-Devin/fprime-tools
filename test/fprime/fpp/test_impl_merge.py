"""
Tests for fprime.fpp.impl_merge

Verifies that newly generated implementation-template members are merged into
existing user implementation files additively, that already-implemented members
are preserved, that brand-new sections are created, and that signature drift is
detected (warn-only).
"""

from fprime.fpp import impl_merge

CLASS = "Foo"

USER_HPP = """\
// ======================================================================
// \\title  Foo.hpp
// ======================================================================

#ifndef Svc_Foo_HPP
#define Svc_Foo_HPP

#include "Svc/Foo/FooComponentAc.hpp"

namespace Svc {

class Foo final : public FooComponentBase {
  public:
    // ----------------------------------------------------------------------
    // Component construction and destruction
    // ----------------------------------------------------------------------

    //! Construct Foo object
    Foo(const char* const compName);

    //! Destroy Foo object
    ~Foo();

  private:
    // ----------------------------------------------------------------------
    // Handler implementations for typed input ports
    // ----------------------------------------------------------------------

    //! Handler implementation for schedIn
    void schedIn_handler(FwIndexType portNum, U32 context) override;

    // a user helper
    void myHelper();
};

}  // namespace Svc

#endif
"""

USER_CPP = """\
// ======================================================================
// \\title  Foo.cpp
// ======================================================================

#include "Svc/Foo/Foo.hpp"

namespace Svc {

// ----------------------------------------------------------------------
// Component construction and destruction
// ----------------------------------------------------------------------

Foo ::Foo(const char* const compName) : FooComponentBase(compName) {}

Foo ::~Foo() {}

// ----------------------------------------------------------------------
// Handler implementations for typed input ports
// ----------------------------------------------------------------------

void Foo ::schedIn_handler(const FwIndexType portNum, U32 context) {
    // my real implementation
    this->doStuff();
}

void Foo ::myHelper() {}

}  // namespace Svc
"""

# Template adds a new port handler (dataIn) and a new command section
# (DO_THING). schedIn keeps the same signature here.
TEMPLATE_HPP = """\
// ======================================================================
// \\title  Foo.hpp
// ======================================================================

#ifndef Svc_Foo_HPP
#define Svc_Foo_HPP

#include "Svc/Foo/FooComponentAc.hpp"

namespace Svc {

class Foo final : public FooComponentBase {
  public:
    // ----------------------------------------------------------------------
    // Component construction and destruction
    // ----------------------------------------------------------------------

    //! Construct Foo object
    Foo(const char* const compName);

    //! Destroy Foo object
    ~Foo();

  private:
    // ----------------------------------------------------------------------
    // Handler implementations for typed input ports
    // ----------------------------------------------------------------------

    //! Handler implementation for schedIn
    void schedIn_handler(FwIndexType portNum, U32 context) override;

    //! Handler implementation for dataIn
    void dataIn_handler(FwIndexType portNum, U32 data) override;

    // ----------------------------------------------------------------------
    // Handler implementations for commands
    // ----------------------------------------------------------------------

    //! Handler implementation for command DO_THING
    void DO_THING_cmdHandler(FwOpcodeType opCode, U32 cmdSeq) override;
};

}  // namespace Svc

#endif
"""

TEMPLATE_CPP = """\
// ======================================================================
// \\title  Foo.cpp
// ======================================================================

#include "Svc/Foo/Foo.hpp"

namespace Svc {

// ----------------------------------------------------------------------
// Component construction and destruction
// ----------------------------------------------------------------------

Foo ::Foo(const char* const compName) : FooComponentBase(compName) {}

Foo ::~Foo() {}

// ----------------------------------------------------------------------
// Handler implementations for typed input ports
// ----------------------------------------------------------------------

void Foo ::schedIn_handler(FwIndexType portNum, U32 context) {
    // TODO
}

void Foo ::dataIn_handler(FwIndexType portNum, U32 data) {
    // TODO
}

// ----------------------------------------------------------------------
// Handler implementations for commands
// ----------------------------------------------------------------------

void Foo ::DO_THING_cmdHandler(FwOpcodeType opCode, U32 cmdSeq) {
    // TODO
    this->cmdResponse_out(opCode, cmdSeq, Fw::CmdResponse::OK);
}

}  // namespace Svc
"""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_parse_cpp_functions_names_and_sections():
    funcs = impl_merge.parse_cpp_functions(TEMPLATE_CPP, CLASS)
    by_name = {f.name: f for f in funcs}
    assert set(by_name) == {
        "Foo",
        "~Foo",
        "schedIn_handler",
        "dataIn_handler",
        "DO_THING_cmdHandler",
    }
    assert by_name["Foo"].section == "Component construction and destruction"
    assert (
        by_name["dataIn_handler"].section
        == "Handler implementations for typed input ports"
    )
    assert (
        by_name["DO_THING_cmdHandler"].section == "Handler implementations for commands"
    )


def test_parse_hpp_functions_names_match_cpp():
    cpp_names = {f.name for f in impl_merge.parse_cpp_functions(TEMPLATE_CPP, CLASS)}
    hpp_names = {f.name for f in impl_merge.parse_hpp_functions(TEMPLATE_HPP, CLASS)}
    assert cpp_names == hpp_names


def test_parse_hpp_param_types():
    funcs = {f.name: f for f in impl_merge.parse_hpp_functions(TEMPLATE_HPP, CLASS)}
    assert funcs["schedIn_handler"].param_types == ["FwIndexType", "U32"]
    assert funcs["DO_THING_cmdHandler"].param_types == ["FwOpcodeType", "U32"]


# ---------------------------------------------------------------------------
# Merge: additive behavior
# ---------------------------------------------------------------------------


def test_merge_cpp_adds_new_members_and_section():
    result = impl_merge.merge_cpp(TEMPLATE_CPP, USER_CPP, CLASS)
    assert set(result.added) == {"dataIn_handler", "DO_THING_cmdHandler"}
    assert result.drifted == []
    assert result.text is not None

    merged_names = {f.name for f in impl_merge.parse_cpp_functions(result.text, CLASS)}
    assert merged_names == {
        "Foo",
        "~Foo",
        "schedIn_handler",
        "myHelper",
        "dataIn_handler",
        "DO_THING_cmdHandler",
    }
    # A single commands section banner is created.
    assert result.text.count("Handler implementations for commands") == 1


def test_merge_hpp_adds_new_members_and_section():
    result = impl_merge.merge_hpp(TEMPLATE_HPP, USER_HPP, CLASS)
    assert set(result.added) == {"dataIn_handler", "DO_THING_cmdHandler"}
    assert result.drifted == []
    assert result.text is not None
    assert result.text.count("Handler implementations for commands") == 1
    assert "DO_THING_cmdHandler" in result.text


def test_merge_preserves_existing_implementation_and_helpers():
    result = impl_merge.merge_cpp(TEMPLATE_CPP, USER_CPP, CLASS)
    # The user's hand-written body is preserved verbatim.
    assert "// my real implementation" in result.text
    assert "this->doStuff();" in result.text
    # The user-only helper is preserved.
    assert "void Foo ::myHelper() {}" in result.text
    # The schedIn handler is not duplicated.
    assert result.text.count("schedIn_handler") == 1


def test_merge_no_changes_returns_none():
    # Merging the user file against a template that only contains members the
    # user already has yields no change.
    template = USER_CPP.replace(
        "void Foo ::schedIn_handler(const FwIndexType portNum, U32 context) {\n"
        "    // my real implementation\n    this->doStuff();\n}",
        "void Foo ::schedIn_handler(FwIndexType portNum, U32 context) {\n    // TODO\n}",
    )
    result = impl_merge.merge_cpp(template, USER_CPP, CLASS)
    assert result.added == []
    assert result.text is None


# ---------------------------------------------------------------------------
# Merge: signature drift (warn-only)
# ---------------------------------------------------------------------------


def test_merge_detects_signature_drift_without_modifying():
    drift_template = TEMPLATE_CPP.replace(
        "void Foo ::schedIn_handler(FwIndexType portNum, U32 context) {",
        "void Foo ::schedIn_handler(FwIndexType portNum, U64 context) {",
    )
    result = impl_merge.merge_cpp(drift_template, USER_CPP, CLASS)
    assert "schedIn_handler" in result.drifted
    # Drifted members are never modified: the original U32 implementation stays.
    assert "U32 context" in result.text
    assert "U64 context" not in result.text


def test_merge_hpp_detects_signature_drift():
    drift_template = TEMPLATE_HPP.replace(
        "void schedIn_handler(FwIndexType portNum, U32 context) override;",
        "void schedIn_handler(FwIndexType portNum, U64 context) override;",
    )
    result = impl_merge.merge_hpp(drift_template, USER_HPP, CLASS)
    assert "schedIn_handler" in result.drifted


# ---------------------------------------------------------------------------
# Merge: includes
# ---------------------------------------------------------------------------


def test_merge_adds_new_includes():
    template = TEMPLATE_HPP.replace(
        '#include "Svc/Foo/FooComponentAc.hpp"',
        '#include "Svc/Foo/FooComponentAc.hpp"\n#include <Os/Mutex.hpp>',
    )
    result = impl_merge.merge_hpp(template, USER_HPP, CLASS)
    assert "#include <Os/Mutex.hpp>" in result.text
    assert any("Os/Mutex.hpp" in inc for inc in result.added_includes)


def test_merge_does_not_duplicate_existing_includes():
    result = impl_merge.merge_hpp(TEMPLATE_HPP, USER_HPP, CLASS)
    assert result.text.count('#include "Svc/Foo/FooComponentAc.hpp"') == 1
    assert result.added_includes == []


# ---------------------------------------------------------------------------
# Merge: multiple brand-new sections keep template order
# ---------------------------------------------------------------------------


def test_merge_multiple_new_sections_preserve_template_order():
    # User has only the ctor/dtor section; the template adds two brand-new
    # sections that both get appended near the namespace close brace.
    user_cpp = """\
// ======================================================================
// \\title  Foo.cpp
// ======================================================================

#include "Svc/Foo/Foo.hpp"

namespace Svc {

// ----------------------------------------------------------------------
// Component construction and destruction
// ----------------------------------------------------------------------

Foo ::Foo(const char* const compName) : FooComponentBase(compName) {}

Foo ::~Foo() {}

}  // namespace Svc
"""
    result = impl_merge.merge_cpp(TEMPLATE_CPP, user_cpp, CLASS)
    assert set(result.added) == {
        "schedIn_handler",
        "dataIn_handler",
        "DO_THING_cmdHandler",
    }
    ports_idx = result.text.index("Handler implementations for typed input ports")
    cmds_idx = result.text.index("Handler implementations for commands")
    # The typed-ports section comes before the commands section, matching the
    # order in the template (not reversed).
    assert ports_idx < cmds_idx
    # Both new sections are created exactly once.
    assert result.text.count("Handler implementations for typed input ports") == 1
    assert result.text.count("Handler implementations for commands") == 1

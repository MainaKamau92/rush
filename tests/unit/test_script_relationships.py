import pytest

from app.services.code_relationships import verifies_relationship

VIEW = """import { api } from "./api";
import Recent, { type Props as RecentProps } from "./recent.component";
import * as time from "../shared/time.js";
import "./style.css";

export function View(props: RecentProps) {
  const when = time.stamp();
  return api("/items").then(() => Recent(props));
}
"""
PATH = "web/src/view.tsx"


@pytest.mark.parametrize(
    ("target", "relationship", "start", "end", "expected"),
    [
        ("web/src/api.ts", "callee", 8, 8, True),
        ("web/src/recent.component.tsx", "callee", 8, 8, True),
        ("web/src/recent.component.tsx", "shared_interface", 6, 6, True),
        # A .js specifier names the compiled file of a .ts source.
        ("web/shared/time.ts", "callee", 7, 7, True),
        ("web/src/api/index.ts", "import", 1, 1, True),
        # The changed lines must use the import, or change the import itself.
        ("web/src/api.ts", "callee", 7, 7, False),
        ("web/src/other.ts", "callee", 8, 8, False),
        ("web/src/api.ts", "configuration", 1, 8, False),
    ],
)
def test_typescript_imports_link_changed_lines_to_their_modules(
    target, relationship, start, end, expected
):
    assert (
        verifies_relationship(PATH, VIEW, target, relationship, start, end) == expected
    )


def test_packages_and_paths_outside_the_repository_are_never_linked():
    source = (
        'import x from "react";\nimport y from "../../../../etc/passwd";\nx(); y();\n'
    )
    assert not verifies_relationship("a/b.ts", source, "react.ts", "callee", 3, 3)
    assert not verifies_relationship("a/b.ts", source, "etc/passwd.ts", "callee", 3, 3)


def test_a_test_or_caller_must_import_and_use_the_changed_module():
    test = 'import { View } from "../src/view";\n\ntest("renders", () => View({}));\n'
    unused = 'import { View } from "../src/view";\n\ntest("nothing", () => 1);\n'
    dynamic = 'const view = await import("../src/view.tsx");\n'
    for target_source, expected in ((test, True), (unused, False), (dynamic, True)):
        assert (
            verifies_relationship(
                PATH, VIEW, "web/tests/view.test.ts", "test", 6, 9, target_source
            )
            == expected
        )
    assert not verifies_relationship(
        PATH, VIEW, "web/tests/view.py", "test", 6, 9, test
    )
    assert not verifies_relationship(PATH, VIEW, "web/tests/x.ts", "caller", 6, 9, None)


def test_hostile_or_unrelated_imports_never_link_and_stay_fast():
    import time

    started = time.monotonic()
    huge = "import " + " " * 200_000 + "x\n" + "export " + "\t" * 200_000 + "\n"
    assert not verifies_relationship(PATH, huge, "web/src/x.ts", "callee", 1, 2)
    assert time.monotonic() - started < 2
    # Commented-out imports, side-effect imports and re-exports are not links.
    caller = (
        '// import { View } from "../src/view";\n'
        'import "../src/view";\n'
        'export * from "../src/view";\n'
        "View();\n"
    )
    assert not verifies_relationship(
        PATH, VIEW, "web/tests/a.ts", "caller", 6, 9, caller
    )
    # The caller must use a name the changed lines define, not just any import.
    other = 'import { setup } from "../src/view";\n\nsetup();\n'
    assert not verifies_relationship(PATH, VIEW, "web/tests/b.ts", "test", 6, 9, other)
    multiline = 'import {\n  View,\n} from "../src/view.mjs";\n\nView({});\n'
    # Multi-line imports parse; a .mjs specifier may name a TypeScript source.
    assert verifies_relationship(PATH, VIEW, "web/tests/c.ts", "test", 6, 9, multiline)
    assert verifies_relationship(
        "web/src/view.mts", VIEW, "web/tests/c.ts", "test", 6, 9, multiline
    )

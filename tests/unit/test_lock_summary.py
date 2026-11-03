import json

from app.services.lock_summary import MAX_LINES, summarize_package_lock


def lock(**packages):
    return json.dumps(
        {"lockfileVersion": 3, "packages": {"": {"name": "app"}} | packages}
    ).encode()


def entry(version, **extra):
    return {
        "version": version,
        "resolved": f"https://registry.npmjs.org/x/-/x-{version}.tgz",
        "integrity": "sha512-fictional",
    } | extra


def test_package_changes_are_listed_with_their_risks():
    old = lock(
        **{
            "node_modules/minimatch": entry("10.2.6", dev=True),
            "node_modules/gone": entry("1.0.0"),
        }
    )
    new = lock(
        **{
            "node_modules/minimatch": entry(
                "11.0.4", dev=True, engines={"node": "20 || >=22"}
            ),
            "node_modules/helper": entry("1.0.3", hasInstallScript=True),
            "node_modules/a/node_modules/b": {
                "version": "2.0.0",
                "resolved": "http://mirror.invalid/b-2.0.0.tgz",
            },
        }
    )
    summary = summarize_package_lock("web/package-lock.json", old, new)
    assert summary is not None
    lines = summary.splitlines()
    assert "web/package-lock.json" in lines[0]
    assert lines[1:] == [
        "+ a > b 2.0.0, from mirror.invalid, no integrity hash",
        "- gone 1.0.0",
        "+ helper 1.0.3, runs an install script",
        "~ minimatch 10.2.6, dev -> 11.0.4, dev, node 20 || >=22",
    ]


def test_a_new_lockfile_unreadable_content_or_no_change_gives_no_summary():
    assert summarize_package_lock("p", None, lock(**{"node_modules/x": entry("1")}))
    assert summarize_package_lock("p", b"\0binary", lock()) is None
    assert summarize_package_lock("p", b"[1]", lock()) is None
    assert summarize_package_lock("p", lock(), lock()) is None


def test_long_summaries_say_how_much_is_hidden():
    many = {f"node_modules/p{i:03}": entry("1.0.0") for i in range(MAX_LINES + 5)}
    summary = summarize_package_lock("p", None, lock(**many))
    assert summary is not None
    assert summary.splitlines()[-1] == "... 5 more package changes not shown"


def test_hostile_lockfiles_cannot_crash_forge_lines_or_grow_unbounded():
    nested = b"[" * 100000 + b"]" * 100000
    assert summarize_package_lock("p", None, nested) is None
    forged = lock(
        **{
            "node_modules/evil\n+ fake 1.0.0": entry("9" * 5000),
            "node_modules/odd": {"version": 1, "engines": {"node": ["x"]}},
        }
    )
    summary = summarize_package_lock("p", None, forged)
    assert summary is not None
    lines = summary.splitlines()
    assert len(lines) == 3
    assert all(len(line) < 300 for line in lines)
    assert lines[1].startswith("+ evil + fake 1.0.0 ") and "…" in lines[1]


def test_a_changed_integrity_hash_at_the_same_version_is_shown():
    old = lock(**{"node_modules/x": entry("1.0.0")})
    new = lock(**{"node_modules/x": entry("1.0.0", integrity="sha512-other")})
    summary = summarize_package_lock("p", old, new)
    assert summary is not None
    assert summary.splitlines()[1] == "~ x 1.0.0, integrity hash changed"

"""Remove files the repository should no longer be carrying.

Where these come from
---------------------
The site is maintained through GitHub's web interface, and "Add file ->
Upload files" puts whatever is dropped on it at the repository root. Over
time that has left half a megabyte there: four copies of a downloaded page
named `index (12).html` through `index (15).html`, two odds payloads, and
root-level duplicates of five files whose real home is craftypicks/data/.

Every one of them is served as a live URL, and the duplicates are worse than
clutter: a root board.json that is three weeks old sits one path away from
the real one, and nothing on the site says which is which.

The rule, deliberately narrow
-----------------------------
Only three kinds of file are ever removed:

  1. A browser's numbered download -- `something (12).html`, `x (3).json.gz`.
     The parenthesised counter is the signature; a file a person named is
     never removed.
  2. A file whose name matches one under craftypicks/data/. The canonical
     copy has to exist for the root one to go, so this can only ever delete
     a duplicate, never the last copy of anything.

  3. A path on the RETIRED list below, under craftypicks/data/. That list
     is written by hand, one exact path at a time, and exists because an
     uploaded archive can add a file but never delete one. It is confined
     to data/ because that is the only place the daily workflow's `git add`
     reaches -- see the long note above RETIRED.

Nothing else, ever. Not a directory, not a dotfile, not README or CNAME, and
nothing at the root outside rules 1 and 2 -- the whole site lives one level
down, and only a path spelled out in RETIRED is reachable there.
"""
from __future__ import annotations

import re
from pathlib import Path

# A browser's "(2)" suffix, before the extension. `index (12).html` and
# `baseball_mlb (11).json.gz` both match; `my notes (draft).md` does not,
# because the counter has to be digits.
NUMBERED = re.compile(r" \(\d+\)(\.[A-Za-z0-9.]+)?$")

# Never removed, whatever else is true of them.
KEEP = {"README.md", "LICENSE", "CNAME", ".gitignore", ".gitattributes",
        "index.html", "404.html", "robots.txt", "sitemap.xml"}

# Files that belonged to a feature this site no longer has, listed by their
# path under craftypicks/. They are removed here rather than by hand because
# the repository is maintained from a phone through GitHub's web UI, where an
# uploaded archive can add and replace files but never delete one -- so a
# retired module would otherwise sit in the tree forever.
#
# ONLY data/. That is not taste, it is what the workflow can commit, and it
# is written down here because getting it wrong took the daily job out for
# two days.
#
# The commit step stages with:
#
#     git add -- data '*.html' ':(exclude)_src/**'
#
# and then refuses to continue if anything matching '*.html' is still
# unstaged. So a deletion under _src/ is made on the runner, never staged,
# and arrives at that check as " D craftypicks/_src/plays.body.html" -- the
# job exits 1 AFTER the odds have been bought, every morning, forever. This
# list named ten such files and did exactly that.
#
# scripts/ has the mirror-image problem and is just as pointless: those
# deletions are not staged either, and not being *.html they do not trip the
# check, so they are re-made and thrown away on every run.
#
# Retiring anything outside data/ therefore needs the workflow's `git add`
# widened first. Until then such files stay on disk, dead and harmless, and
# come out by hand through the GitHub UI. The self-test enforces the rule so
# it cannot be rediscovered the hard way a second time.
RETIRED = (
    "data/plays.json",
    "data/history.json",
    "data/stats.json",
    # The home-runs-allowed board, retired 2026-09-21. The page goes through
    # the build's own orphan sweep; this is the data behind it.
    "data/homers.json",
)

def retired(site: Path) -> list[Path]:
    """The RETIRED paths that still exist under `site` (craftypicks/)."""
    out = []
    for rel in RETIRED:
        path = site / rel
        if path.is_file():
            out.append(path)
    return out


def strays(root: Path, data: Path) -> list[Path]:
    """Files at `root` that are a numbered download or a duplicate of data/."""
    if not root.is_dir():
        return []
    canonical = {p.name for p in data.glob("*")} if data.is_dir() else set()
    out = []
    for path in sorted(root.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.name in KEEP:
            continue
        stem = path.name
        if NUMBERED.search(stem) or stem in canonical:
            out.append(path)
    return out


def run(root: Path, data: Path, verbose: bool = True) -> int:
    removed = 0
    for path in retired(data.parent) + strays(root, data):
        try:
            path.unlink()
        except OSError as e:                                 # noqa: PERF203
            if verbose:
                print(f"!! tidy: could not remove {path.name} ({e})")
            continue
        if verbose:
            print(f"   tidy: removed {path.name}")
        removed += 1
    if verbose and removed:
        print(f"-- tidy: {removed} stray file(s) removed from the repo root")
    return removed


def _self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        data = root / "craftypicks" / "data"
        data.mkdir(parents=True)
        (data / "board.json").write_text("{}")
        (data / "slate.json").write_text("{}")

        for name in ("index (12).html", "index (15).html",
                     "baseball_mlb (11).json.gz", "board.json", "slate.json",
                     "README.md", "index.html", "CNAME", "notes (draft).md",
                     "keepme.json"):
            (root / name).write_text("x")
        (root / ".gitignore").write_text("x")
        (root / "craftypicks").mkdir(exist_ok=True)

        found = {p.name for p in strays(root, data)}
        assert found == {"index (12).html", "index (15).html",
                         "baseball_mlb (11).json.gz", "board.json",
                         "slate.json"}, found
        # The things that must survive, named one at a time so a failure says
        # which rule broke.
        assert "README.md" not in found
        assert "index.html" not in found, "the site's own front page"
        assert "CNAME" not in found
        assert ".gitignore" not in found, "dotfiles are never touched"
        assert "notes (draft).md" not in found, \
            "the counter has to be digits -- a person's parenthesis is not one"
        assert "keepme.json" not in found, \
            "a root file with no twin in data/ is somebody's file"

        # A retired file goes too, and one that is already gone is not an
        # error.
        (data / "plays.json").write_text("x")
        assert [q.name for q in retired(data.parent)] == ["plays.json"]

        assert run(root, data, verbose=False) == 6
        assert not (data / "plays.json").exists()
        assert not retired(data.parent), "second run finds nothing"
        assert not strays(root, data), "second run finds nothing"
        assert (root / "keepme.json").exists()
        assert (data / "board.json").exists(), \
            "the canonical copy is the one being protected, not deleted"

        # A duplicate whose canonical copy does NOT exist stays put: this can
        # only ever delete a second copy, never the last one.
        (root / "orphan.json").write_text("x")
        assert not strays(root, data)

        # Nothing below the root is reachable from here at all.
        assert (data / "slate.json").exists()
        assert run(Path(tmp) / "nope", data, verbose=False) == 0

    # Every retired path has to be one the daily workflow's `git add` will
    # actually stage, or tidy deletes it on the runner and the commit step
    # fails its "built pages that were not staged" check -- after the odds
    # have been bought. Ten _src/ entries on this list did exactly that,
    # every morning, and it was found in the Actions log rather than here.
    for rel in RETIRED:
        assert rel.startswith("data/"), (
            f"{rel} is outside data/, which the workflow's git add does not "
            f"reach. Widen the git add in daily.yml first, or remove the "
            f"file by hand instead of listing it here.")

    print("tidy self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()

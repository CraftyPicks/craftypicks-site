"""Remove downloads that were committed to the repository root by mistake.

Where these come from
---------------------
The site is maintained through GitHub's web interface, and "Add file ->
Upload files" puts whatever is dropped on it at the repository root. Over
time that has left half a megabyte there: four copies of a downloaded page
named `index (12).html` through `index (15).html`, two odds payloads, and
root-level duplicates of five files whose real home is craftypicks/data/.

Every one of them is served as a live URL, and the duplicates are worse than
clutter: a root plays.json that is three weeks old sits one path away from
the real one, and nothing on the site says which is which.

The rule, deliberately narrow
-----------------------------
Only two kinds of file are ever removed, and only from the repository root:

  1. A browser's numbered download -- `something (12).html`, `x (3).json.gz`.
     The parenthesised counter is the signature; a file a person named is
     never removed.
  2. A file whose name matches one under craftypicks/data/. The canonical
     copy has to exist for the root one to go, so this can only ever delete
     a duplicate, never the last copy of anything.

Nothing else, ever. Not a directory, not a dotfile, not README or CNAME, and
nothing outside the root -- the whole site lives one level down, so a bug
here cannot reach it.
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
    for path in strays(root, data):
        try:
            path.unlink()
        except OSError as e:                                 # noqa: PERF203
            if verbose:
                print(f"!! tidy: could not remove {path.name} ({e})")
            continue
        if verbose:
            print(f"   tidy: removed ./{path.name}")
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
        (data / "plays.json").write_text("{}")
        (data / "slate.json").write_text("{}")

        for name in ("index (12).html", "index (15).html",
                     "baseball_mlb (11).json.gz", "plays.json", "slate.json",
                     "README.md", "index.html", "CNAME", "notes (draft).md",
                     "keepme.json"):
            (root / name).write_text("x")
        (root / ".gitignore").write_text("x")
        (root / "craftypicks").mkdir(exist_ok=True)

        found = {p.name for p in strays(root, data)}
        assert found == {"index (12).html", "index (15).html",
                         "baseball_mlb (11).json.gz", "plays.json",
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

        assert run(root, data, verbose=False) == 5
        assert not strays(root, data), "second run finds nothing"
        assert (root / "keepme.json").exists()
        assert (data / "plays.json").exists(), \
            "the canonical copy is the one being protected, not deleted"

        # A duplicate whose canonical copy does NOT exist stays put: this can
        # only ever delete a second copy, never the last one.
        (root / "orphan.json").write_text("x")
        assert not strays(root, data)

        # Nothing below the root is reachable from here at all.
        assert (data / "slate.json").exists()
        assert run(Path(tmp) / "nope", data, verbose=False) == 0

    print("tidy self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()

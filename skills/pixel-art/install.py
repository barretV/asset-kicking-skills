"""Copy this skill into another repository or skills root.

    python install.py --into ../other-game
    python install.py --into ../other-game --claude
    python install.py --into ~/.agents

Default target is `<repo>/.agents/skills/pixel-art`, which is one of the two paths agent
tooling actually discovers (`--claude` writes to `<repo>/.claude/skills/pixel-art` instead).
Pass `--into ~/.agents` to install globally, for every project.
Refuses to overwrite an existing install unless --force is given, so it is safe to point at
a repo you have already set up.

This copies the skill (docs, craft rules, CLI). It does not build Aseprite or install the
MCP server; see SETUP.md for those, then run bin/verify.py.
"""
import argparse
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "pixel-art"
IGNORE = shutil.ignore_patterns(
    "__pycache__",
    "*.pyc",
    "_pebbly-sparse",
    ".venv",
    "art",
    "dist",
)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--into", required=True, help="target repository root or skills root")
    ap.add_argument("--claude", action="store_true", help="install into .claude/skills")
    ap.add_argument("--force", action="store_true", help="overwrite an existing install")
    args = ap.parse_args()

    repo = os.path.abspath(os.path.expanduser(args.into))
    if not os.path.isdir(repo):
        sys.exit("not a directory: %s" % repo)
    # `--into ~/.agents` (a skills root, not a repo) must not become ~/.agents/.agents/...
    base = os.path.basename(os.path.normpath(repo))
    if args.claude:
        parts = ("skills", NAME) if base == ".claude" else (".claude", "skills", NAME)
    else:
        parts = ("skills", NAME) if base == ".agents" else (".agents", "skills", NAME)
    dest = os.path.join(repo, *parts)
    if os.path.abspath(dest) == HERE:
        sys.exit("source and destination are the same directory")
    if os.path.exists(dest) and not args.force:
        sys.exit("%s already exists - pass --force to replace it" % dest)

    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest):
        shutil.rmtree(dest)
    shutil.copytree(HERE, dest, ignore=IGNORE)

    print("installed to %s" % dest)
    print("next, in %s:" % repo)
    rel = os.path.relpath(dest, repo).replace(os.sep, "/")
    py = "py -3" if os.name == "nt" else "python3"
    print("  %s %s/bin/verify.py" % (py, rel))
    print("  register the aseprite MCP server (see %s/SETUP.md)" % rel)
    print("  set ASEPRITE_PATH if aseprite.exe is not on PATH or in <repo>/aseprite/build/bin")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Copy the skills in skills/ to where coding agents look for them.

    python install_skills.py --global                    # ~/.claude/skills and ~/.agents/skills (every project)
    python install_skills.py --project ../my-game        # <repo>/.claude/skills and <repo>/.agents/skills
    python install_skills.py --project ../my-game --only pixel-art,blender-anim
    python install_skills.py --global --claude-only      # just ~/.claude/skills
    python install_skills.py --list

Claude Code reads `.claude/skills/<name>/SKILL.md` (project) and `~/.claude/skills/` (global). Cursor, Codex and
other agents read `.agents/skills/`. A copy in any other folder is never loaded. Existing installs are kept
unless --force is given. Only copies files: installs no software and downloads nothing.
"""
import argparse
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.join(HERE, "skills")
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "renders", "_tiles")


def available():
    return sorted(d for d in os.listdir(SKILLS) if os.path.isfile(os.path.join(SKILLS, d, "SKILL.md")))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    where = ap.add_mutually_exclusive_group()
    where.add_argument("--global", dest="glob", action="store_true", help="install for every project")
    where.add_argument("--project", help="install into this repository")
    where.add_argument("--list", action="store_true")
    ap.add_argument("--only", help="comma list of skill names")
    ap.add_argument("--claude-only", action="store_true", help="skip the .agents copy")
    ap.add_argument("--agents-only", action="store_true", help="skip the .claude copy")
    ap.add_argument("--force", action="store_true", help="replace existing installs")
    a = ap.parse_args()

    names = available()
    if a.list or not (a.glob or a.project):
        print("skills:", ", ".join(names))
        if not a.list:
            print("pass --global or --project <repo> to install")
        return
    if a.only:
        want = [n.strip() for n in a.only.split(",") if n.strip()]
        bad = [n for n in want if n not in names]
        if bad:
            sys.exit("unknown skill(s): %s" % ", ".join(bad))
        names = want

    base = os.path.expanduser("~") if a.glob else os.path.abspath(a.project)
    if not os.path.isdir(base):
        sys.exit("not a directory: %s" % base)
    roots = []
    if not a.agents_only:
        roots.append(os.path.join(base, ".claude", "skills"))
    if not a.claude_only:
        roots.append(os.path.join(base, ".agents", "skills"))

    for root in roots:
        for name in names:
            dest = os.path.join(root, name)
            if os.path.exists(dest) and not a.force:
                print("keep   %s (exists; --force to replace)" % dest)
                continue
            if os.path.exists(dest):
                shutil.rmtree(dest)
            os.makedirs(root, exist_ok=True)
            shutil.copytree(os.path.join(SKILLS, name), dest, ignore=IGNORE)
            print("copied %s" % dest)
    print("Restart the agent (or open a new session) so it picks the skills up.")


if __name__ == "__main__":
    main()

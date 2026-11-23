"""Copy this skill into another repository.

    python skills/blender-anim/install.py --into ../other-game
    python skills/blender-anim/install.py --into ../other-game --claude

Default target is `<repo>/.agents/skills/blender-anim`, which is one of the two paths agent
tooling actually discovers (`--claude` writes to `<repo>/.claude/skills/blender-anim` instead).
Pass `--into ~/.agents` to install globally, for every project.
Refuses to overwrite an existing install unless --force is given, so it is safe to point at a
repo you have already set up.
"""
import argparse
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
IGNORE = shutil.ignore_patterns('__pycache__', '*.pyc', 'renders', '_tiles')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--into', required=True, help='target repository root')
    ap.add_argument('--claude', action='store_true', help='install into .claude/skills')
    ap.add_argument('--force', action='store_true', help='overwrite an existing install')
    args = ap.parse_args()

    repo = os.path.abspath(args.into)
    if not os.path.isdir(repo):
        sys.exit('not a directory: %s' % repo)
    # `--into ~/.agents` (a skills root, not a repo) must not become ~/.agents/.agents/...
    base = os.path.basename(os.path.normpath(repo))
    if args.claude:
        parts = ('skills', 'blender-anim') if base == '.claude' else ('.claude', 'skills', 'blender-anim')
    else:
        parts = ('skills', 'blender-anim') if base == '.agents' else ('.agents', 'skills', 'blender-anim')
    dest = os.path.join(repo, *parts)
    if os.path.abspath(dest) == HERE:
        sys.exit('source and destination are the same directory')
    if os.path.exists(dest) and not args.force:
        sys.exit('%s already exists - pass --force to replace it' % dest)

    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest):
        shutil.rmtree(dest)
    shutil.copytree(HERE, dest, ignore=IGNORE)

    print('installed to %s' % dest)
    print('next, in %s:' % repo)
    rel = os.path.relpath(dest, repo).replace(os.sep, '/')
    print('  blender -b --python-exit-code 1 -P %s/bin/discover_rig.py -- <character.glb>' % rel)
    print('  blender -b --python-exit-code 1 -P %s/bin/verify.py -- <character.glb>' % rel)


if __name__ == '__main__':
    main()

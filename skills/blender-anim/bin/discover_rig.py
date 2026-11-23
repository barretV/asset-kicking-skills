"""Propose a `rig.json` for a character GLB: axes, bone chains, floor, fps.

Run inside Blender:

    blender -b --python-exit-code 1 -P bin/discover_rig.py -- model.glb [out.rig.json]

It writes a config next to the model and **prints the table it inferred** - read that table.
Discovery is a good first guess, not an authority: a wrong chain shows up immediately in
`bin/verify.py` as a left/right asymmetry, and every field can be corrected by hand.

How the guess is made
---------------------
* Character frame. A character is symmetric about its sagittal plane, so the mesh is searched
  for the plane it mirrors onto itself best; that plane's normal is LAT, and FWD is the other
  horizontal axis. Symmetry cannot decide *which* side is the character's right, so the sign is
  a config decision - if left and right come out swapped, negate `lat`.
* Limb chains. Bones with no children are leaves (hands, feet, head). Walking four joints up
  from each leaf gives a candidate limb; a limb whose joints sit high and far off the midline is
  an arm, one that sits low is a leg. Sign of the lateral offset decides which side.
* Spine and head. Whatever lies on the path from the root to the head leaf.
* Floor. Lowest vertex of the rest mesh, which is where a foot-lock pass should hold the soles.
"""
import json
import math
import os
import sys

import bpy
from mathutils import Matrix, Vector
from mathutils.kdtree import KDTree

argv = sys.argv[sys.argv.index('--') + 1:]
FLIP = '--flip-sides' in argv
argv = [a for a in argv if not a.startswith('--')]
GLB = os.path.abspath(argv[0])
OUT = os.path.abspath(argv[1]) if len(argv) > 1 else os.path.splitext(GLB)[0] + '.rig.json'

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
bpy.ops.import_scene.gltf(filepath=GLB)

arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
mesh = max((o for o in bpy.data.objects if o.type == 'MESH'), key=lambda o: len(o.data.vertices))
bones = arm.data.bones
children = {b.name: [c.name for c in b.children] for b in bones}
roots = [b.name for b in bones if b.parent is None]
root = roots[0] if roots else bones[0].name

print('armature %s: %d bones, %d roots (%s); mesh %s: %d verts'
      % (arm.name, len(bones), len(roots), ', '.join(roots), mesh.name, len(mesh.data.vertices)))

# ---- the character's frame: find the plane the mesh mirrors onto itself about ----------
UP = Vector((0, 0, 1))
pts = [mesh.matrix_world @ v.co for v in mesh.data.vertices]


def symmetry_score(yaw_deg):
    """Median nearest-neighbour distance between the mesh and its mirror about `yaw`."""
    lat = Matrix.Rotation(math.radians(yaw_deg), 3, UP) @ Vector((1, 0, 0))
    kd = KDTree(len(pts))
    for i, p in enumerate(pts):
        kd.insert(p, i)
    kd.balance()
    ds = []
    for p in pts[::3]:
        m = p - 2.0 * p.dot(lat) * lat
        ds.append(kd.find(m)[2])
    ds.sort()
    return ds[len(ds) // 2]


scores = [(symmetry_score(y), y) for y in range(0, 180, 5)]
scores.sort()
BEST_YAW = scores[0][1]
print('symmetry: best mirror plane normal is %d deg about UP (residual %.1f mm); '
      'next best %.1f mm at %d deg'
      % (BEST_YAW, scores[0][0] * 1000, scores[1][0] * 1000, scores[1][1]))
if scores[1][0] - scores[0][0] < 0.002:
    print('  WARNING: no clear symmetry plane - the mesh may be asymmetric or not centred; '
          'set axes in the config by hand')

LAT = (Matrix.Rotation(math.radians(BEST_YAW), 3, UP) @ Vector((1, 0, 0))).normalized()
FWD = (Matrix.Rotation(math.radians(BEST_YAW), 3, UP) @ Vector((0, 1, 0))).normalized()

# Symmetry gives the plane, not which side is the character's right. Bone names often do:
# a rig with .L/.R (or _l/_r) suffixes settles it, so the config comes out correct by itself.
import re
# Match both the short form (`.L`, `_R`) and the spelled-out form (`LeftArm`, `RightUpLeg`).
# The spelled-out form matters: SkinTokens emits `LeftShoulder`/`RightArm`, and missing it here
# leaves left/right a coin flip on a rig that actually states the answer.
_token = re.compile(r'(?:^|[._\- ])(left|right|[LR])(?=$|[._\- ]|[A-Z])', re.IGNORECASE)
_tok_lat = {'R': [], 'L': []}
for b in bones:
    m = _token.search(b.name)
    if m:
        _tok_lat[m.group(1)[0].upper()].append((b.head_local - bones[root].head_local).dot(LAT))
if _tok_lat['R'] and _tok_lat['L']:
    r_mean = sum(_tok_lat['R']) / len(_tok_lat['R'])
    l_mean = sum(_tok_lat['L']) / len(_tok_lat['L'])
    if r_mean < l_mean:
        print('bone names say left/right is the other way round - flipping LAT/FWD')
        LAT, FWD = -LAT, -FWD
else:
    print('bone names carry no .L/.R suffix: left/right is a coin flip in this guess - if the'
          ' sides come out swapped, negate axes.lat in the config')

# ---- classify bones in the character frame -------------------------------------------
base = bones[root].head_local
rows = []
for b in bones:
    p = b.head_local - base
    rows.append((b.name, p.dot(LAT), p.dot(FWD), p.dot(UP),
                 len(children[b.name]), (b.tail_local - b.head_local).length))

zs = [r[3] for r in rows]
HEIGHT = (max(zs) - min(zs)) or 1.0


def chain_up(leaf, count=8):
    """Bones from the branch point down to `leaf`, ordered shoulder/hip first.

    Stops at the first parent with more than one child: that is where the limb joins the
    trunk (a hip or a shoulder). A *fixed* bone count is wrong in both directions -- on a
    3-bone arm it prepends the spine, and on a 4-bone tail it truncates it.
    """
    out, name = [], leaf
    while name is not None and len(out) < count:
        out.append(name)
        parent = bones[name].parent.name if bones[name].parent else None
        if parent is None or len(children[parent]) > 1:
            break
        name = parent
    return list(reversed(out))


leaves = [b.name for b in bones if not children[b.name]]
candidates = []
for leaf in leaves:
    ch = chain_up(leaf)
    if len(ch) < 2:
        continue
    lat_mid = sum(r[1] for r in rows if r[0] in ch) / len(ch)
    z_top = next(r[3] for r in rows if r[0] == ch[0])
    candidates.append((leaf, ch, lat_mid, z_top))

# A limb is a chain that stands well off the midline (that alone rules out the head/spine),
# and arms attach above the pelvis while legs attach at or below it - the one cue that does
# not depend on limb length or naming.
limbs = [c for c in candidates if abs(c[2]) > 0.08 * HEIGHT]
right = sorted([c for c in limbs if c[2] > 0], key=lambda c: -abs(c[2]))
left = sorted([c for c in limbs if c[2] < 0], key=lambda c: -abs(c[2]))
print('\ncandidate limbs (chain, mean lateral offset, height of top joint; HEIGHT %.3f):' % HEIGHT)
for leaf, ch, lat_mid, z_top in sorted(candidates, key=lambda c: c[2]):
    end_z = next(r[3] for r in rows if r[0] == leaf)
    kind = 'arm' if end_z > 0.0 else 'leg'
    print('  %-14s lat %+.3f  start z %+.3f  end z %+.3f  [%s]  %s'
          % (leaf, lat_mid, z_top, end_z, kind, ' -> '.join(ch)))

# Arm or leg? Compare where the chain *ends*, not where it starts. A hip's top joint sits
# slightly above the pelvis, so a "top above the pelvis = arm" test claims the legs as arms
# (it did, on a rig whose hips are 0.10 above the root). Hands always hang above feet, so on
# each side the highest-ending chain is the arm and the lowest-ending is the leg. No
# threshold, no dependence on limb length.
z_end = {c[0]: next(r[3] for r in rows if r[0] == c[0]) for c in candidates}
arms, legs = {}, {}
used = set()
for side, cands in (('R', right), ('L', left)):
    if not cands:
        continue
    ordered = sorted(cands, key=lambda c: -z_end[c[0]])
    if len(ordered) == 1:
        only = ordered[0]
        if z_end[only[0]] > 0.0:
            arms[side] = only[1]
        else:
            legs[side] = only[1]
        used.update(only[1])
        continue
    arms[side] = ordered[0][1]
    legs[side] = ordered[-1][1]
    used.update(ordered[0][1])
    used.update(ordered[-1][1])

# ---- spine / head: the trunk leaf closest to the top of the character ------------------
# Not "the highest chain": a tail attaches to the hips *above* the pelvis bottom and is
# longer than the path to the head, so ranking whole chains by their top joint picks the
# tail on any creature with one. The head is the highest leaf left over once the limbs are
# claimed, and the spine is the trunk path from the root to it.
trunk_leaves = [b for b in leaves if b not in used]
z_of = {r[0]: r[3] for r in rows}
head_leaf = max(trunk_leaves, key=lambda n: z_of[n]) if trunk_leaves else None
head, spine = [], []
if head_leaf:
    head = [head_leaf]
    path, name = [], head_leaf
    while name is not None and name != root:
        path.append(name)
        name = bones[name].parent.name if bones[name].parent else None
    path.reverse()
    spine = [b for b in path if b != head_leaf]

if FLIP:
    print('flipping sides: negating LAT/FWD and swapping the R/L chain labels')
    LAT, FWD = -LAT, -FWD
    arms = {('L' if k == 'R' else 'R'): v for k, v in arms.items()}
    legs = {('L' if k == 'R' else 'R'): v for k, v in legs.items()}

ground = min(p.z for p in pts)
cfg = {
    '_note': 'Written by discover_rig.py. Check the printed table; fix anything wrong by hand. '
             'If left and right come out swapped, negate axes.lat.',
    'axes': {'lat': [round(LAT.x, 5), round(LAT.y, 5), round(LAT.z, 5)],
             'fwd': [round(FWD.x, 5), round(FWD.y, 5), round(FWD.z, 5)],
             'up': [0, 0, 1]},
    'chains': {'root': root,
               'spine': spine,
               'head': head,
               'arms': arms,
               'legs': legs},
    'ground': round(ground, 4),
    'fps': bpy.context.scene.render.fps,
    'clips': sorted(a.name for a in bpy.data.actions),
}

print('\nproposed config:')
print(json.dumps(cfg, indent=2))
with open(OUT, 'w', encoding='utf-8') as fh:
    json.dump(cfg, fh, indent=2)
print('\nWROTE:', OUT)

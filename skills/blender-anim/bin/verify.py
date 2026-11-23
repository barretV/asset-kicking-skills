"""Check the things that actually bite: weights, loop seams, left/right symmetry, ground.

    blender -b --python-exit-code 1 -P bin/verify.py -- model.glb [--clips Walk,Idle]
                                                        [--loop Walk,Idle] [--frames 5]

Exits non-zero if a check fails, so it can gate a rebuild. Every number it prints is a
measurement, not an opinion:

  weights   sum of skin weights per vertex. Must be 1: a vertex at 2 is driven twice and the
            limb deforms to roughly double its pose (this is what "the arm melted" looks like).
  seam      per-bone pose difference between a loop clip's first and last frame. A loop that
            does not close hitches once per cycle.
  mirror    left limb versus right limb, after reflecting through the character's sagittal
            plane. Geometry AND skinning both count, so this is the honest answer to "is it
            symmetric?".
  ground    lowest vertex per frame against the rest floor. Below it means a foot is through
            the floor.
"""
import os
import sys

import bpy
from mathutils import Vector
from mathutils.kdtree import KDTree

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'lib'))
import rigmap  # noqa: E402

argv = sys.argv[sys.argv.index('--') + 1:]
GLB = os.path.abspath(argv[0])


def opt(name, default):
    if name in argv:
        return argv[argv.index(name) + 1]
    return default


CLIPS = [c for c in opt('--clips', '').split(',') if c] or None
LOOPS = {c for c in opt('--loop', 'Walk,Idle').split(',') if c}
# Clips are not always mirrored at the same frame: a walk is a cross-body gait (the left arm
# follows the right half a cycle later) and a two-punch combo alternates. Compare with the
# clip's own offset, or every such clip is reported as broken when it is doing its job.
PHASE = {}
for item in [c for c in opt('--phase', '').split(',') if c]:
    name, _, frames = item.partition('=')
    PHASE[name] = int(frames)
SAMPLES = int(opt('--frames', '5'))
TOL_WEIGHT = float(opt('--tol-weight', '0.01'))
TOL_SEAM = float(opt('--tol-seam', '0.002'))          # metres of joint travel
TOL_MIRROR = float(opt('--tol-mirror', '0.025'))      # metres, median
TOL_GROUND = float(opt('--tol-ground', '0.005'))      # metres

rig = rigmap.Rig.load(GLB)
failures = []

print('rig config: %s' % rig.config_path)
print('axes lat=%s fwd=%s' % (tuple(round(v, 3) for v in rig.LAT),
                              tuple(round(v, 3) for v in rig.FWD)))

# ---- weights ----------------------------------------------------------------
sums = [sum(g.weight for g in v.groups) for v in rig.mesh.data.vertices]
bad = sum(1 for s in sums if abs(s - 1.0) > TOL_WEIGHT)
worst = max(abs(s - 1.0) for s in sums) if sums else 0.0
print('\nweights: %d/%d vertices off by >%.3f (worst %.4f)'
      % (bad, len(sums), TOL_WEIGHT, worst))
if bad:
    failures.append('%d vertices with weight sum != 1' % bad)

# ---- per clip ---------------------------------------------------------------
actions = [a for a in bpy.data.actions if rigmap.has_bones(a)]
if CLIPS:
    actions = [a for a in actions if a.name in CLIPS]
print('\nclips: %s' % ', '.join(a.name for a in actions))

origin = rig.arm.pose.bones[rig.ROOT].head.copy()


def mirror(p):
    return (p - origin) - 2.0 * (p - origin).dot(rig.LAT) * rig.LAT + origin


print('\n%-10s %-6s %10s %10s %10s %10s' % ('clip', 'frames', 'seam(mm)', 'mirror(mm)', 'lowest', 'floor'))
for act in actions:
    rig.assign_slot(act)
    f0, f1 = rigmap.clip_range(act)

    # seam: compare the pose at f0 with the pose at f1
    seam = 0.0
    if act.name in LOOPS:
        def pose_points(frame):
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            out = []
            for name in rig.ARMS.get('L', ()) + rig.ARMS.get('R', ()) + rig.LEGS.get('L', ()) \
                    + rig.LEGS.get('R', ()):
                pb = rig.arm.pose.bones[name]
                out.append(pb.head.copy())
                out.append(pb.tail.copy())
            return out
        a = pose_points(f0)
        b = pose_points(f1)
        seam = max((x - y).length for x, y in zip(a, b)) if a else 0.0

    # mirror: left limb against the reflected right limb, at the clip's own phase offset
    step = max(1, (f1 - f0) // max(1, SAMPLES - 1))
    shift = PHASE.get(act.name, 0)
    mirrors, lows = [], []

    def wrapped(frame):
        if act.name not in LOOPS:
            return max(f0, min(f1, frame))
        span = max(1, f1 - f0)
        return f0 + ((frame - f0) % span)

    for f in range(f0, f1 + 1, step):
        bpy.context.scene.frame_set(f)
        bpy.context.view_layer.update()
        origin = rig.arm.pose.bones[rig.ROOT].head.copy()
        right_now = {label: rig.weighted_points(chains['R'], 0.5)
                     for label, chains in (('arms', rig.ARMS), ('legs', rig.LEGS))
                     if 'R' in chains}
        low = rig.lowest_z()

        bpy.context.scene.frame_set(wrapped(f + shift))
        bpy.context.view_layer.update()
        for label, chains in (('arms', rig.ARMS), ('legs', rig.LEGS)):
            if 'R' not in chains or 'L' not in chains:
                continue
            r_pts = right_now.get(label) or []
            l_pts = rig.weighted_points(chains['L'], 0.5)
            if not r_pts or not l_pts:
                continue
            kd = KDTree(len(l_pts))
            for i, p in enumerate(l_pts):
                kd.insert(p, i)
            kd.balance()
            ds = sorted(kd.find(mirror(p))[2] for p in r_pts)
            mirrors.append((label, ds[len(ds) // 2]))
        lows.append(low)

    worst_mirror, word = (0.0, '-')
    if mirrors:
        label, worst_mirror = max(mirrors, key=lambda kv: kv[1])
        word = label
    low = min(lows) if lows else 0.0
    print('%-10s %-6s %10.1f %10.1f %10.3f %10.3f%s'
          % (act.name, '%d-%d' % (f0, f1), seam * 1000, worst_mirror * 1000,
             low, rig.GROUND, '  (%s)' % word if word != '-' else ''))

    if act.name in LOOPS and seam > TOL_SEAM:
        failures.append('%s loop seam %.1f mm' % (act.name, seam * 1000))
    if worst_mirror > TOL_MIRROR:
        failures.append('%s %s mirror %.1f mm' % (act.name, word, worst_mirror * 1000))
    if low < rig.GROUND - TOL_GROUND:
        failures.append('%s goes %.1f mm through the floor' % (act.name, (rig.GROUND - low) * 1000))

print('')
if failures:
    print('FAIL')
    for f in failures:
        print('  - ' + f)
    sys.exit(1)
print('PASS - all checks within tolerance')

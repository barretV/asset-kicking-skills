"""Make one side of a rig do what the other side does, mirrored - for whole clips.

    blender -b --python-exit-code 1 -P bin/mirror_clips.py -- in.glb out.glb \\
        --chains arms --loop Walk,Idle --phase Walk=12,Punch=-16

Why rotations are copied rather than "the same yaw numbers": this class of rig is modelled with
one arm raised and one hanging, its bones have arbitrary rolls, and the two chains differ in
length. Equal relative rotations therefore produce unequal poses. Copying the reflected *world*
matrix of the source bone and keeping the target joint where it is transfers the pose itself.

Conventions that matter (each one cost a pass, see SKILL.md):
  * reflect the rotation with S = I - 2·LAT·LATᵀ about the *body's* lateral axis for that frame,
    then rebuild the target matrix from the reflected basis. Reflecting all three columns
    instead gives det = -1 and the export splits it into a rotation plus a negative scale.
  * every frame gets a key. glTF bakes, and a sparse keying leaves the old pose in between.
  * key immediately; with an active action a depsgraph update re-evaluates the fcurves and
    throws away a pose that was set but not keyed.
  * a looping clip's left side usually follows out of phase (half a cycle for a walk), which is
    what --phase is for; a negative shift makes the left side lead.
"""
import math
import os
import sys

import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'lib'))
import rigmap  # noqa: E402

argv = sys.argv[sys.argv.index('--') + 1:]
GLB_IN, GLB_OUT = argv[0], os.path.abspath(argv[1])


def opt(name, default):
    return argv[argv.index(name) + 1] if name in argv else default


CHAINS = [c.strip() for c in opt('--chains', 'arms').split(',') if c.strip()]
LOOPS = {c.strip() for c in opt('--loop', 'Walk,Idle').split(',') if c.strip()}
PHASE = {}
for item in [c for c in opt('--phase', '').split(',') if c]:
    name, _, frames = item.partition('=')
    PHASE[name] = int(frames)
ONLY = [c.strip() for c in opt('--clips', '').split(',') if c.strip()]

rig = rigmap.Rig.load(GLB_IN)
scene = bpy.context.scene
arm = rig.arm

for act in bpy.data.actions:
    act.use_fake_user = True

pairs = []
for label in CHAINS:
    chains = getattr(rig, label.upper())
    if 'R' not in chains or 'L' not in chains:
        print('skip %s: no L/R pair in the config' % label)
        continue
    pairs.extend(list(zip(chains['R'], chains['L'])))
if not pairs:
    raise SystemExit('nothing to mirror - check chains in %s' % rig.config_path)
print('mirroring %d bone pairs: %s' % (len(pairs), ', '.join('%s<-' % l for r, l in pairs)))


def basis(frame, names):
    """Bone matrices (armature space) at a frame, sampled in one go.

    Whole matrices, not just the rotations: a mirrored pose needs the joint in the mirrored
    place as well. Anchoring each bone at its current head keeps it on the *old* pose, which
    is how the first version of this file wrote a correct-looking arm in the wrong position.
    """
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    return {n: arm.pose.bones[n].matrix.copy() for n in names}


actions = [a for a in bpy.data.actions if rigmap.has_bones(a)]
if ONLY:
    actions = [a for a in actions if a.name in ONLY]

for act in actions:
    rig.assign_slot(act)
    f0, f1 = rigmap.clip_range(act)
    shift = PHASE.get(act.name, 0)
    loop = act.name in LOOPS
    # A loop is written through f1 as well: f1 must repeat f0, or the clip hitches once per
    # cycle no matter how good the individual frames are. (Missing this put a 355 mm jump in
    # the walk's seam.)
    last = f1 + 1
    src_names = [r for r, _l in pairs]

    for f in range(f0, last):
        if loop:
            src = f0 + ((f - shift - f0) % max(1, (f1 - f0)))
        else:
            src = max(f0, min(f1, f - shift))
        rots = basis(src, src_names)

        scene.frame_set(f)
        bpy.context.view_layer.update()
        lat = Vector(rig.body_axes().col[0]).normalized()
        S = Matrix.Identity(3)
        for i in range(3):
            for j in range(3):
                S[i][j] -= 2.0 * lat[i] * lat[j]          # reflection about the body's LAT
        origin = arm.pose.bones[rig.ROOT].head.copy()     # the plane passes through the body
        for rname, lname in pairs:
            pb = arm.pose.bones[lname]
            src = rots[rname]
            M = (S @ src.to_3x3().normalized() @ S).to_4x4()
            M.translation = origin + S @ (src.translation - origin)
            pb.rotation_mode = 'QUATERNION'
            pb.matrix = M
            pb.keyframe_insert('rotation_quaternion', frame=f)
            pb.keyframe_insert('location', frame=f)
            bpy.context.view_layer.update()               # after the key, never before
    print('  %s: %d frames mirrored%s%s'
          % (act.name, last - f0, ' (loop)' if loop else '',
             ' shift %+d' % shift if shift else ''))

# ---- self-check: the mirror is exact at the BONE level, whatever the mesh does ---------
# A mesh-level check (bin/verify.py) measures pose *and* sculpture: a character whose left arm
# is a different sculpt cannot score zero there no matter how perfect the mirroring is. This
# check isolates the part this script is responsible for.
print('')
worst_pos = worst_rot = 0.0
for act in actions:
    rig.assign_slot(act)
    f0, f1 = rigmap.clip_range(act)
    shift = PHASE.get(act.name, 0)
    loop = act.name in LOOPS
    span = max(1, f1 - f0)
    for f in range(f0, f1 + 1, max(1, span // 8)):
        src_frame = f0 + ((f - shift - f0) % span) if loop else max(f0, min(f1, f - shift))
        scene.frame_set(f)
        bpy.context.view_layer.update()
        lat = Vector(rig.body_axes().col[0]).normalized()
        S = Matrix.Identity(3)
        for i in range(3):
            for j in range(3):
                S[i][j] -= 2.0 * lat[i] * lat[j]
        origin = arm.pose.bones[rig.ROOT].head.copy()
        left_now = {l: arm.pose.bones[l].matrix.copy() for _r, l in pairs}
        ref = basis(src_frame, [r for r, _l in pairs])
        for rname, lname in pairs:
            want = (S @ ref[rname].to_3x3().normalized() @ S).to_4x4()
            want.translation = origin + S @ (ref[rname].translation - origin)
            got = left_now[lname]
            worst_pos = max(worst_pos, (got.translation - want.translation).length)
            dq = (got.to_3x3().normalized() @ want.to_3x3().normalized().inverted()).to_quaternion()
            worst_rot = max(worst_rot, math.degrees(abs(dq.angle)))
print('bone-level mirror error: %.3f mm, %.2f deg' % (worst_pos * 1000, worst_rot))

rig.clear_pose()
scene.frame_set(1)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.export_scene.gltf(filepath=GLB_OUT, export_format='GLB',
                          export_animations=True, export_animation_mode='ACTIONS',
                          export_frame_range=False, export_anim_slide_to_zero=True,
                          export_morph=True)
print('WROTE:', GLB_OUT)

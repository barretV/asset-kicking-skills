"""Move animation clips from one rig onto another rig -- any character, any topology.

    blender -b --python-exit-code 1 -P bin/retarget_clips.py -- \
        old_animated.glb new_rigged.glb out.glb [--map overrides.json] [--renders DIR]

Use this when the *motion* is good but the body changed: a resculpt, a different
proportions pass, a model you re-rigged. Re-authoring clips by hand throws away the
timing that made them work; transferring rotation arcs keeps it.

How it works
------------
Per bone and per frame, in world space:

    delta     = idle_world(bone)^-1 @ pose_world(bone, f)      # motion vs the rig's own stance
    delta_l   = C_src^-1 @ delta @ C_src                       # into the CHARACTER's frame
    delta_dst = C_dst @ delta_l @ C_dst^-1                     # back out, in the new character
    wanted    = rest_world_dst(bone) @ delta_dst

Expressing the motion in the character's own frame is the whole trick. The two rigs
are almost never in the same world orientation (one may be yawed 40 deg inside its
armature, the other axis-aligned), so a raw world-space copy swings every limb the
wrong way. `rig.json` carries each character's frame (`axes.lat/fwd/up`), which
`bin/discover_rig.py` derives from the mesh's mirror plane -- so this works without
you measuring anything.

Chain lengths do not have to match. The last bone of a shorter limb takes the last
(dEEPEST) bone of the longer one, because a bone's world rotation already contains its
parents' bends: folding is lossless when the dropped bones carry no *local* rotation,
and this script measures and reports that instead of assuming it.

Clips are ground-solved by default: the new limbs are a different length, so the
transferred bob no longer puts the soles on the floor.

Notes
-----
* Both rigs need a `<model>.rig.json`; run `bin/discover_rig.py` on each first.
* The source needs an `Idle` clip (or `--ref CLIP`) -- it defines the stance every
  delta is measured from. Without a stable stance reference the whole transfer
  inherits a constant lean.
"""
import argparse
import json
import os
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'lib'))
from rigmap import Rig, clip_range, fcurves_of  # noqa: E402


def axis_matrix(rig):
    """Basis with columns (right, forward, up), as a quaternion."""
    m = Matrix((
        (rig.LAT.x, rig.FWD.x, rig.UP.x),
        (rig.LAT.y, rig.FWD.y, rig.UP.y),
        (rig.LAT.z, rig.FWD.z, rig.UP.z),
    ))
    return m.to_quaternion().normalized()


def sample_points(rig, step=5):
    """Subsampled world-space mesh points, for bbox/feature size."""
    mw = rig.mesh.matrix_world
    vs = rig.mesh.data.vertices
    return [mw @ vs[i].co for i in range(0, len(vs), step)]


def sample(rig, min_bones=True):
    """Every bone-bearing action: per frame world rotations + root world position."""
    clips = {}
    if rig.arm.animation_data is None:
        rig.arm.animation_data_create()
    for act in list(bpy.data.actions):
        if not any(fc.data_path.startswith('pose.bones') for fc in fcurves_of(act)):
            continue
        rig.arm.animation_data.action = act
        fs, fe = clip_range(act)
        frames, roots = {}, {}
        for f in range(int(fs), int(fe) + 1):
            bpy.context.scene.frame_set(f)
            bpy.context.view_layer.update()
            frames[f] = {pb.name: pb.matrix.to_quaternion().copy()
                         for pb in rig.arm.pose.bones}
            roots[f] = (rig.arm.matrix_world @ rig.arm.pose.bones[rig.ROOT].matrix).translation.copy()
        clips[act.name] = (int(fs), int(fe), frames, roots)
        print('  sampled %-10s frames %d..%d' % (act.name, fs, fe))
    if not clips:
        raise SystemExit('no bone actions in the source file')
    return clips


def build_map(src, dst, overrides, src_bones):
    """Old bone -> new bone, from the two rig.json chain tables.

    `src_bones` is passed in because the source objects are deleted before this runs --
    reading `src.arm` here raises ReferenceError on a removed StructRNA.
    """
    m = {}
    m[src.ROOT] = dst.ROOT
    if src.HEAD and dst.HEAD:
        m[src.HEAD[-1]] = dst.HEAD[-1]
    if src.SPINE and dst.SPINE:
        m[src.SPINE[-1]] = dst.SPINE[-1]

    def limbs(a, b, label):
        for side in sorted(set(a) & set(b)):
            s, d = list(a[side]), list(b[side])
            if not s or not d:
                continue
            for i in range(min(len(s), len(d)) - 1):
                m[s[i]] = d[i]
            # the deepest bones fold together (cumulative world rotation)
            m[s[-1]] = d[-1]
            if len(s) != len(d):
                print('  %s %s: %d bones -> %d, folded %s onto %s'
                      % (label, side, len(s), len(d), s[-1], d[-1]))
        for side in sorted(set(a) - set(b)):
            print('  WARNING: source has %s %s with no counterpart in the target'
                  % (label, side))
    limbs(src.ARMS, dst.ARMS, 'arm')
    limbs(src.LEGS, dst.LEGS, 'leg')

    for k, v in (overrides or {}).items():
        m[k] = v
    missing_src = [b for b in m if b not in src_bones]
    missing_dst = [b for b in m.values() if b not in dst.arm.pose.bones]
    if missing_src:
        raise SystemExit('mapping names bones missing from the SOURCE: %s' % missing_src)
    if missing_dst:
        raise SystemExit('mapping names bones missing from the TARGET: %s' % missing_dst)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('dst')
    ap.add_argument('out')
    ap.add_argument('--map', help='JSON {old_bone: new_bone} overrides')
    ap.add_argument('--ref', default='Idle', help='clip whose first frame is the stance (default Idle)')
    ap.add_argument('--renders', help='directory for verification stills')
    ap.add_argument('--no-ground', action='store_true', help='skip the foot-lock solve')
    ap.add_argument('--views', default='3q,front', help='render views (front back side 3q)')
    args = ap.parse_args([a for a in sys.argv[sys.argv.index('--') + 1:]] if '--' in sys.argv else [])
    if args.renders:
        # absolute: Blender resolves a relative render.filepath against something else
        args.renders = os.path.abspath(args.renders)

    src_glb = os.path.abspath(args.src)
    dst_glb = os.path.abspath(args.dst)
    out_glb = os.path.abspath(args.out)
    overrides = {}
    if args.map:
        with open(args.map) as fh:
            overrides = json.load(fh)

    # ---- source: sample the motion, then throw the object away --------------
    print('[retarget] source %s' % os.path.basename(src_glb))
    src = Rig.load(src_glb)
    src_ground = src.GROUND
    clips = sample(src)
    if args.ref not in clips:
        raise SystemExit('reference clip %r not found; have %s (pass --ref)'
                         % (args.ref, sorted(clips)))
    src.arm.animation_data.action = bpy.data.actions[args.ref]
    ref_f0 = clips[args.ref][0]
    bpy.context.scene.frame_set(ref_f0)
    bpy.context.view_layer.update()
    Q_IDLE = {pb.name: pb.matrix.to_quaternion().copy() for pb in src.arm.pose.bones}
    ROOT_IDLE = (src.arm.matrix_world @ src.arm.pose.bones[src.ROOT].matrix).translation.copy()
    C_src = axis_matrix(src)
    rest_src = {b.name: (src.arm.matrix_world @ b.matrix_local).to_quaternion().normalized()
                for b in src.arm.data.bones}
    src_bones = set(rest_src)
    src_points = sample_points(src, 5)

    # How much *local* rotation does each bone carry? A bone with none is a pure
    # pass-through, so folding it into its child loses nothing. A bone that bends on its
    # own is real motion, and folding it away is a visible loss -- hence the report.
    # Folding child into parent is lossless when the child adds no motion of its own.
    # Measure exactly that: the difference between the two bones' world rotation deltas.
    # (A "local rotation vs rest" number is misleading here -- it mixes in the root's
    # motion and reads ~0 on a skeleton that is clearly moving.)
    print('[retarget] extra motion a child carries beyond its parent (0 = pure pass-through):')
    extra = {}
    for b in src.arm.data.bones:
        if b.parent is None or b.name not in Q_IDLE:
            continue
        worst = 0.0
        for _c, (_fs, _fe, frames, _r) in clips.items():
            for q in frames.values():
                dp = (Q_IDLE[b.parent.name].inverted() @ q[b.parent.name]).normalized()
                dc = (Q_IDLE[b.name].inverted() @ q[b.name]).normalized()
                worst = max(worst, dp.rotation_difference(dc).angle)
        extra[b.name] = worst
    for name, ang in sorted(extra.items(), key=lambda kv: -kv[1])[:6]:
        print('     %-16s %5.1f deg' % (name, ang))
    print('     (a bone near 0 that gets folded away loses nothing; a large value would)')

    # ---- target -------------------------------------------------------------
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for a in list(bpy.data.actions):
        bpy.data.actions.remove(a)
    print('[retarget] target %s' % os.path.basename(dst_glb))
    dst = Rig.load(dst_glb)

    # ---- align the target into the source's world frame ---------------------
    # Rotate/scale/shift the whole target rig so both characters share one frame, then
    # transfer deltas directly in world space. Conjugating each delta between the two
    # character frames is equivalent in theory and was measurably NOT equivalent here:
    # Idle transferred within 17 deg but walk/punch diverged past 100 deg. Aligning the
    # rig physically is the path that has been checked against renders, and it leaves the
    # output in the same orientation as the source, which is what a game expects anyway.
    Rm = axis_matrix(src).to_matrix() @ axis_matrix(dst).to_matrix().transposed()
    dp = sample_points(dst, 5)
    sp = src_points
    s_lo = Vector((min(p[i] for p in sp) for i in range(3)))
    s_hi = Vector((max(p[i] for p in sp) for i in range(3)))
    d_lo = Vector((min(p[i] for p in dp) for i in range(3)))
    d_hi = Vector((max(p[i] for p in dp) for i in range(3)))
    scale = (s_hi.z - s_lo.z) / max(d_hi.z - d_lo.z, 1e-6)
    rot = [Rm @ Vector(p) * scale for p in (d_lo, d_hi)]
    shift = Vector(((s_lo.x + s_hi.x) / 2 - (rot[0].x + rot[1].x) / 2,
                    (s_lo.y + s_hi.y) / 2 - (rot[0].y + rot[1].y) / 2,
                    s_lo.z - rot[0].z))
    M = Matrix.Translation(shift) @ (Rm * scale).to_4x4()
    for obj in (dst.arm, dst.mesh):
        obj.parent = None
        obj.matrix_world = M @ obj.matrix_world
    for obj in (dst.arm, dst.mesh):
        for o in bpy.context.selected_objects:
            o.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    dst.mesh.parent = dst.arm
    dst.mesh.matrix_parent_inverse = dst.arm.matrix_world.inverted()
    print('[retarget] scale %.4f  yaw %.1f deg  shift (%+.3f %+.3f %+.3f)'
          % (scale, Rm.to_quaternion().angle * 57.2958, shift.x, shift.y, shift.z))

    rest_dst = {b.name: (dst.arm.matrix_world @ b.matrix_local).to_quaternion().normalized()
                for b in dst.arm.data.bones}
    rest_m = {b.name: (dst.arm.matrix_world @ b.matrix_local).copy() for b in dst.arm.data.bones}
    parent_of = {b.name: (b.parent.name if b.parent else None) for b in dst.arm.data.bones}

    mapping = build_map(src, dst, overrides, src_bones)
    print('[retarget] %d bones mapped' % len(mapping))

    order, queue = [], [b for b in dst.arm.data.bones if b.parent is None]
    while queue:
        b = queue.pop(0)
        order.append(b.name)
        queue.extend(list(b.children))
    rel_rest = {n: (rest_dst[parent_of[n]].inverted() @ rest_dst[n]).normalized()
                for n in order if parent_of[n]}

    if dst.arm.animation_data is None:
        dst.arm.animation_data_create()
    for pb in dst.arm.pose.bones:
        pb.rotation_mode = 'QUATERNION'

    wanted_for = {v: k for k, v in mapping.items()}

    # ---- write --------------------------------------------------------------
    actions = {}
    for cname in sorted(clips):
        _fs, _fe, frames, roots = clips[cname]
        act = bpy.data.actions.new(cname)
        actions[cname] = act
        dst.arm.animation_data.action = act
        for f in sorted(frames):
            bpy.context.scene.frame_set(f)
            pose_q = {}
            for nm in order:
                pb = dst.arm.pose.bones[nm]
                src_name = wanted_for.get(nm)
                if src_name is None:
                    pb.matrix_basis = Matrix.Identity(4)
                    pose_q[nm] = (pose_q[pb.parent.name] @ rel_rest[nm]) if pb.parent \
                        else rest_dst[nm]
                    continue
                delta_w = (Q_IDLE[src_name].inverted() @ frames[f][src_name]).normalized()
                desired = (rest_dst[nm] @ delta_w).normalized()
                base = (pose_q[pb.parent.name] @ rel_rest[nm]) if pb.parent else rest_dst[nm]
                m = (base.inverted() @ desired).to_matrix().to_4x4()
                if src_name == src.ROOT:
                    bob = roots[f] - ROOT_IDLE
                    m.translation = rest_m[nm].to_quaternion().inverted() @ bob
                pb.matrix_basis = m
                pose_q[nm] = desired
                pb.keyframe_insert('rotation_quaternion', frame=f)
                if src_name == src.ROOT:
                    pb.keyframe_insert('location', frame=f)
        print('  wrote   %-10s %d frames' % (cname, len(frames)))

    # ---- foot lock ----------------------------------------------------------
    if not args.no_ground:
        for cname in sorted(clips):
            _fs, _fe, frames, _roots = clips[cname]
            dst.arm.animation_data.action = actions[cname]
            pb = dst.arm.pose.bones[dst.ROOT]
            axis = rest_m[dst.ROOT].to_quaternion().inverted()
            gaps = []
            for f in sorted(frames):
                bpy.context.scene.frame_set(f)
                bpy.context.view_layer.update()
                gaps.append((f, src_ground - dst.lowest_z()))
            print('  %-10s floor gap before solve: %+.3f .. %+.3f'
                  % (cname, min(g for _f, g in gaps), max(g for _f, g in gaps)))
            for f, dz in gaps:
                bpy.context.scene.frame_set(f)
                bpy.context.view_layer.update()
                pb.location = pb.location + axis @ Vector((0.0, 0.0, dz))
                pb.keyframe_insert('location', frame=f)

    ref_name = args.ref if args.ref in actions else sorted(actions)[0]
    dst.arm.animation_data.action = actions[ref_name]
    bpy.context.scene.frame_set(clips[ref_name][0])

    # ---- report -------------------------------------------------------------
    print('\n[retarget] lowest mesh point after solve (want %+.3f):' % src_ground)
    for cname in sorted(clips):
        dst.arm.animation_data.action = actions[cname]
        fs, fe, _f, _r = clips[cname]
        zs = []
        for f in range(fs, fe + 1, max(1, (fe - fs) // 4)):
            bpy.context.scene.frame_set(f)
            bpy.context.view_layer.update()
            zs.append(dst.lowest_z())
        print('     %-10s %s' % (cname, ' '.join('%+.3f' % z for z in zs)))
    dst.arm.animation_data.action = actions[ref_name]
    bpy.context.scene.frame_set(clips[ref_name][0])

    # ---- renders ------------------------------------------------------------
    if args.renders:
        # the target now sits in the SOURCE's world frame, so the cameras must use the
        # source's axes -- the target's own config axes describe where it *was*, and using
        # them films the character from behind.
        render_stills(dst, actions, clips, args, (src.LAT, src.FWD))

    # ---- export -------------------------------------------------------------
    for o in bpy.context.selected_objects:
        o.select_set(False)
    dst.arm.select_set(True)
    dst.mesh.select_set(True)
    bpy.context.view_layer.objects.active = dst.arm
    bpy.ops.export_scene.gltf(filepath=out_glb, export_format='GLB', use_selection=True,
                              export_animations=True, export_animation_mode='ACTIONS')
    print('[retarget] WROTE %s' % out_glb)


def render_stills(dst, actions, clips, args, axes):
    LAT, FWD = axes
    """A few frames per clip from fixed cameras, for eyeballing the transfer."""
    scene = bpy.context.scene
    os.makedirs(args.renders, exist_ok=True)
    engines = {e.identifier for e in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items}
    scene.render.engine = 'BLENDER_EEVEE_NEXT' if 'BLENDER_EEVEE_NEXT' in engines else 'BLENDER_EEVEE'
    scene.render.resolution_x = scene.render.resolution_y = 620
    if scene.world is None:
        scene.world = bpy.data.worlds.new('W')
    scene.world.use_nodes = True
    scene.world.node_tree.nodes['Background'].inputs[0].default_value = (0.09, 0.10, 0.12, 1)
    for nm, e in (('key', 3.0), ('fill', 1.4)):
        d = bpy.data.lights.new(nm, 'SUN')
        d.energy = e
        o = bpy.data.objects.new(nm, d)
        scene.collection.objects.link(o)
        o.rotation_euler = (0.9, 0.1, 0.7) if nm == 'key' else (1.2, 0.0, -1.1)
    pts = dst.evaluated_points()
    lo = Vector((min(p[i] for p in pts) for i in range(3)))
    hi = Vector((max(p[i] for p in pts) for i in range(3)))
    target = (lo + hi) * 0.5
    span = max((hi - lo).length, 0.001)
    cd = bpy.data.cameras.new('C')
    cd.type = 'ORTHO'
    cd.ortho_scale = span * 1.15
    cam = bpy.data.objects.new('C', cd)
    scene.collection.objects.link(cam)
    scene.camera = cam
    views = {'3q': (FWD * 0.85 + LAT * 0.45).normalized(),
             'front': FWD.copy(),
             'side': LAT.copy(),
             'back': -FWD}
    for cname in sorted(clips):
        dst.arm.animation_data.action = actions[cname]
        fs, fe, _f, _r = clips[cname]
        picks = sorted({fs, fs + (fe - fs) // 3, fs + 2 * (fe - fs) // 3, fe})
        for v in [x.strip() for x in args.views.split(',') if x.strip()]:
            cam.location = target + views[v] * span * 2.0
            cam.rotation_euler = (target - cam.location).normalized().to_track_quat('-Z', 'Y').to_euler()
            for f in picks:
                scene.frame_set(f)
                scene.render.filepath = os.path.join(
                    args.renders, '%s_%s_%02d.png' % (cname.lower(), v, f))
                bpy.ops.render.render(write_still=True)
        print('  rendered %s' % cname)


if __name__ == '__main__':
    main()

"""Report what every bone of a rig actually owns. Run this before animating anything.

    blender -b --python-exit-code 1 -P bin/audit_rig.py -- rigged.glb [--png out.png]

A learned rigger names bones from its own vocabulary, and the names are frequently
wrong: on one creature sculpt a 4-bone chain labelled `RightUpLeg -> RightLeg ->
RightFoot -> RightToeBase` was the **tail** (18,000 vertices, reaching a body-length
backwards), and the second leg was left as `bone_12..14`. Keying a retarget off those
names drives the tail as a leg.

Ownership cannot lie. This prints, per bone: how many vertices it dominates, where
those vertices are in world space, and how big that region is. A bone you expected to
own nothing that owns 10% of the mesh is the tell.

Also prints the weight-quality numbers worth comparing between two rigs:
influences per vertex, unweighted vertices, and how many are effectively rigid.
"""
import argparse
import sys

import bpy
from mathutils import Vector


def main():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument('glb')
    ap.add_argument('--png', help='render the skeleton over a ghosted body')
    ap.add_argument('--views', default='3q,front')
    a = ap.parse_args(argv)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=a.glb)
    arm = next((o for o in bpy.data.objects if o.type == 'ARMATURE'), None)
    if arm is None:
        sys.exit('no armature in %s -- the mesh is not rigged' % a.glb)
    mesh = max((o for o in bpy.data.objects if o.type == 'MESH'),
               key=lambda o: len(o.data.vertices))
    me = mesh.data
    mw = mesh.matrix_world

    gname = {g.index: g.name for g in mesh.vertex_groups}
    owned = {b.name: [] for b in arm.data.bones}
    infl = []
    unweighted = 0
    rigid = 0
    for v in me.vertices:
        gs = [g for g in v.groups if g.weight > 1e-4]
        infl.append(len(gs))
        if not gs:
            unweighted += 1
            continue
        best = max(gs, key=lambda g: g.weight)
        if best.weight > 0.995:
            rigid += 1
        nm = gname.get(best.group)
        if nm in owned:
            owned[nm].append(mw @ v.co)

    n = len(me.vertices)
    print('=' * 100)
    print('%s   %d verts, %d bones, %d groups'
          % (a.glb.split('/')[-1].split('\\')[-1], n, len(arm.data.bones), len(mesh.vertex_groups)))
    print('weights: %.2f influences/vert, %d unweighted, %.1f%% near-rigid (>0.995)'
          % (sum(infl) / max(n, 1), unweighted, 100.0 * rigid / max(n, 1)))
    print('-' * 100)
    print('%-16s %-16s %7s  %-26s %-26s' % ('bone', 'parent', 'verts', 'head (world)',
                                            'centroid of what it owns'))
    print('-' * 100)
    for b in arm.data.bones:
        pts = owned[b.name]
        h = arm.matrix_world @ b.head_local
        if pts:
            c = sum(pts, Vector()) / len(pts)
            cs = '(%+.2f %+.2f %+.2f)' % (c.x, c.y, c.z)
        else:
            cs = '-'
        print('%-16s %-16s %7d  (%+.2f %+.2f %+.2f)     %-24s'
              % (b.name, b.parent.name if b.parent else '-', len(pts), h.x, h.y, h.z, cs))

    empty = [b.name for b in arm.data.bones if not owned[b.name]]
    if empty:
        print('\nbones that own NOTHING (deform bone with no weight): %s' % empty)
    print('\nRead the centroids: long chains marching away from the body are tails, not legs.\n'
          'Vertices are grouped by dominant bone, so each centroid is where that region sits.')

    if a.png:
        render_overlay(arm, mesh, a.png, a.views)


def render_overlay(arm, mesh, png, views):
    scene = bpy.context.scene
    engines = {e.identifier for e in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items}
    scene.render.engine = 'BLENDER_EEVEE_NEXT' if 'BLENDER_EEVEE_NEXT' in engines else 'BLENDER_EEVEE'
    scene.render.resolution_x = scene.render.resolution_y = 900
    if scene.world is None:
        scene.world = bpy.data.worlds.new('W')
    scene.world.use_nodes = True
    scene.world.node_tree.nodes['Background'].inputs[0].default_value = (0.05, 0.06, 0.08, 1)

    ghost = bpy.data.materials.new('ghost')
    ghost.use_nodes = True
    bsdf = ghost.node_tree.nodes['Principled BSDF']
    bsdf.inputs['Base Color'].default_value = (0.55, 0.60, 0.70, 1)
    bsdf.inputs['Alpha'].default_value = 0.16
    ghost.blend_method = 'BLEND'
    mesh.data.materials.clear()
    mesh.data.materials.append(ghost)
    arm.show_in_front = True

    pts = [mesh.matrix_world @ v.co for v in mesh.data.vertices[::7]]
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

    dirs = {'front': Vector((0, -1, 0.1)), 'side': Vector((1, 0, 0.1)),
            '3q': Vector((0.9, -0.55, 0.25)), 'back': Vector((0, 1, 0.1))}
    for v in [x.strip() for x in views.split(',') if x.strip()]:
        d = dirs.get(v, dirs['3q']).normalized()
        cam.location = target + d * span * 2.0
        cam.rotation_euler = (target - cam.location).normalized().to_track_quat('-Z', 'Y').to_euler()
        scene.render.filepath = png.replace('.png', '_%s.png' % v)
        bpy.ops.render.render(write_still=True)
        print('rendered', scene.render.filepath)


if __name__ == '__main__':
    main()

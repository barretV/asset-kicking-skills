"""Render chosen frames of a clip side by side from one orthographic camera.

Comparison, not beauty: one camera, one light, one scale, flat material, so a difference
between two tiles is a difference in the pose. That is what makes it possible to say "the left
arm is wrong" without arguing about lighting.

    blender -b --python-exit-code 1 -P bin/render_ab.py -- model.glb Idle 3q out.png 1 19

Views are built from the character's own axes (`rig.json`), not the armature's:
  front, 3q, 3qm, side, sidem, back, top
`3qm` is the mirror of `3q` about the body's plane of symmetry: a pose that is a true mirror of
another, seen from the mirrored camera, must produce the same image. Comparing `3q` with `3qm`
is the cheapest test that a mirror really is a mirror.
"""
import os
import sys

import bpy
import numpy as np
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'lib'))
import rigmap  # noqa: E402

argv = sys.argv[sys.argv.index('--') + 1:]
GLB, CLIP, VIEW, OUTP = argv[0], argv[1], argv[2], os.path.abspath(argv[3])
FRAMES = [int(a) for a in argv[4:]] or [1]
RES = int(os.environ.get('AB_RES', '420'))
FLAT = os.environ.get('AB_FLAT', '1') != '0'

rig = rigmap.Rig.load(GLB)
scene = bpy.context.scene
scene.render.engine = 'BLENDER_EEVEE'
scene.render.resolution_x = RES
scene.render.resolution_y = RES
scene.render.film_transparent = False

world = bpy.data.worlds.new('W')
world.use_nodes = True
world.node_tree.nodes['Background'].inputs[0].default_value = (0.19, 0.21, 0.25, 1)
scene.world = world
for rot, energy in (((1.15, 0, 0.45), 5.0), ((1.35, 0, -1.1), 2.4), ((1.5, 0, 2.4), 1.6)):
    sun = bpy.data.objects.new('Sun', bpy.data.lights.new('Sun', 'SUN'))
    sun.data.energy = energy
    sun.rotation_euler = rot
    scene.collection.objects.link(sun)

if FLAT:
    rig.mesh.data.materials.clear()
    mat = bpy.data.materials.new('flat')
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes['Principled BSDF']
    bsdf.inputs['Base Color'].default_value = (0.42, 0.86, 0.80, 1)
    bsdf.inputs['Roughness'].default_value = 0.55
    rig.mesh.data.materials.append(mat)

# ---- framing from the rest silhouette --------------------------------------
rig.clear_pose()
bpy.context.view_layer.update()
pts = rig.evaluated_points()
center = sum(pts, Vector()) / len(pts)
lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
size = (hi - lo).length
target = (lo + hi) * 0.5

DIRS = {
    'front': rig.FWD,
    'back': -rig.FWD,
    'side': rig.LAT,
    'sidem': -rig.LAT,
    '3q': (rig.FWD * 0.72 + rig.LAT * 0.62).normalized(),
    '3qm': (rig.FWD * 0.72 - rig.LAT * 0.62).normalized(),
    'top': rig.UP,
}
if VIEW not in DIRS:
    raise SystemExit('unknown view %r; pick one of %s' % (VIEW, ', '.join(DIRS)))

cd = bpy.data.cameras.new('C')
cd.type = 'ORTHO'
cd.ortho_scale = size * 0.92
cam = bpy.data.objects.new('C', cd)
scene.collection.objects.link(cam)
scene.camera = cam
cam.location = target + DIRS[VIEW] * size * 2.0
cam.rotation_euler = (target - cam.location).normalized().to_track_quat('-Z', 'Y').to_euler()

act = bpy.data.actions.get(CLIP) or next((a for a in bpy.data.actions if CLIP in a.name), None)
if act is None:
    raise SystemExit('no clip %r; actions are %s'
                     % (CLIP, ', '.join(a.name for a in bpy.data.actions)))
rig.assign_slot(act)
print('clip %s frames %s of %s' % (CLIP, FRAMES, tuple(act.frame_range)))

TMP = os.path.join(os.path.dirname(OUTP), '_tiles')
os.makedirs(TMP, exist_ok=True)
tiles = []
for f in FRAMES:
    scene.frame_set(f)
    p = os.path.join(TMP, '%s_%s_%03d.png' % (CLIP, VIEW, f))
    scene.render.filepath = p
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(p, check_existing=False)
    w, h = img.size
    buf = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    tiles.append(buf.reshape(h, w, 4)[::-1].copy())
    bpy.data.images.remove(img)

pad = 4
cols = len(tiles)
W = cols * RES + (cols + 1) * pad
canvas = np.zeros((RES + pad * 2, W, 4), dtype=np.float32)
canvas[..., 3] = 1.0
for i, arr in enumerate(tiles):
    x = pad + i * (RES + pad)
    canvas[pad:pad + RES, x:x + RES] = arr

img = bpy.data.images.new('strip', width=W, height=RES + pad * 2, alpha=True)
img.pixels.foreach_set(canvas[::-1].ravel())
img.filepath_raw = OUTP
img.file_format = 'PNG'
img.save()
print('WROTE', OUTP, 'frames', FRAMES)

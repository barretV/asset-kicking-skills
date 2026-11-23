"""
Clay renders of a sculpt donor in the model's frame, on the CPU (Cycles device CPU: no GPU job), for the
before / sculpt / after sheets. The alignment (yaw, scale, offset) comes from hi3d_compare.py's json.

    blender -b --factory-startup -P bin/hi3d_render.py -- <in.glb> <align.json> <out_prefix>
            [--views 3q,side,front,back] [--max-faces 400000] [--size 450x350]

Writes <out_prefix>-<view>.png. Views: 3q (three-quarter), side, front, back.
"""
import json
import math
import sys

import bpy
from mathutils import Euler, Matrix, Vector

argv = sys.argv[sys.argv.index("--") + 1:]
src, align_path, out = argv[:3]
opt = lambda k, d: argv[argv.index(k) + 1] if k in argv else d
views = opt("--views", "3q,side,front,back").split(",")
max_faces = int(opt("--max-faces", "400000"))
W, H = (int(x) for x in opt("--size", "450x350").split("x"))
al = json.load(open(align_path))

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
clay = bpy.data.materials.new("clay")
clay.use_nodes = True
bsdf = clay.node_tree.nodes["Principled BSDF"]
bsdf.inputs["Base Color"].default_value = (0.62, 0.6, 0.68, 1)
bsdf.inputs["Roughness"].default_value = 0.7
for o in meshes:
    if len(o.data.polygons) > max_faces:
        m = o.modifiers.new("dec", 'DECIMATE')
        m.ratio = max_faces / len(o.data.polygons)
    o.data.materials.clear()
    o.data.materials.append(clay)

# game frame (Y up, Z fwd) -> Blender (Z up, -Y fwd); hi3d_compare applied: yaw about up, uniform scale, offset
root = bpy.data.objects.new("align", None)
bpy.context.scene.collection.objects.link(root)
for o in meshes:
    if o.parent is None:
        o.parent = root
s = al["scale"]
root.matrix_world = Matrix.Translation(Vector((al["offset"][0], -al["offset"][2], al["offset"][1]))) @ \
    Matrix.Rotation(math.radians(al["yaw"]), 4, 'Z') @ Matrix.Scale(s, 4)

box = al["model_box"]                       # game axes
cx, cy, cz = [(b[0] + b[1]) / 2 for b in box]
centre = Vector((cx, -cz, cy))
radius = max(b[1] - b[0] for b in box) * 0.75

sc = bpy.context.scene
sc.render.engine = 'CYCLES'
sc.cycles.device = 'CPU'
sc.cycles.samples = 24
sc.cycles.use_denoising = True
sc.render.resolution_x, sc.render.resolution_y = W, H
sc.render.film_transparent = False
world = bpy.data.worlds.new("w")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.07, 0.05, 0.11, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 0.6
sc.world = world
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", 'SUN'))
sun.data.energy = 3.5
sun.rotation_euler = Euler((math.radians(50), 0, math.radians(30)))
sc.collection.objects.link(sun)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
cam.data.lens = 50
sc.collection.objects.link(cam)
sc.camera = cam
# yaw in degrees from the front (+Z game = -Y Blender), pitch up
VIEWS = {"3q": (35, 22), "side": (90, 10), "front": (0, 15), "back": (180, 30), "top": (0, 85)}
for v in views:
    yaw_d, pitch_d = VIEWS[v]
    y, p = math.radians(yaw_d), math.radians(pitch_d)
    d = radius * 2.2
    pos = centre + Vector((math.sin(y) * math.cos(p), -math.cos(y) * math.cos(p), math.sin(p))) * d
    cam.location = pos
    cam.rotation_euler = (centre - pos).to_track_quat('-Z', 'Y').to_euler()
    sun.rotation_euler = Euler((math.radians(50), 0, y + math.radians(30)))
    sc.render.filepath = f"{out}-{v}.png"
    bpy.ops.render.render(write_still=True)
    print("[ok]", sc.render.filepath)

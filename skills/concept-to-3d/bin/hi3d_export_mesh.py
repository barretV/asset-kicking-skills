"""
Dump a GLB's triangles (rest pose, world space, game axes: +Y up, +Z forward) to an .npz for the CPU-only
sculpt tools (bin/hi3d_compare.py). One array pair per mesh object: <name>__v (N,3) float32,
<name>__f (M,3) int32. Optionally decimates very dense sculpts first (Hi3D 1024 is ~2-4M faces).

    blender -b --factory-startup -P bin/hi3d_export_mesh.py -- <in.glb> <out.npz> [--max-faces 400000]
"""
import sys

import bpy
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:]
src, out = argv[0], argv[1]
max_faces = int(argv[argv.index("--max-faces") + 1]) if "--max-faces" in argv else 0

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
for o in bpy.context.scene.objects:
    if o.type == 'ARMATURE':
        o.data.pose_position = 'REST'
bpy.context.view_layer.update()

arrays = {}
for o in [o for o in bpy.context.scene.objects if o.type == 'MESH']:
    if max_faces and len(o.data.polygons) > max_faces:
        m = o.modifiers.new("dec", 'DECIMATE')
        m.ratio = max_faces / len(o.data.polygons)
    dg = bpy.context.evaluated_depsgraph_get()
    ev = o.evaluated_get(dg)
    me = ev.to_mesh()
    me.calc_loop_triangles()
    v = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", v)
    v = v.reshape(-1, 3)
    mw = np.array(o.matrix_world, np.float32)
    v = v @ mw[:3, :3].T + mw[:3, 3]
    v = np.stack([v[:, 0], v[:, 2], -v[:, 1]], 1)          # Blender Z-up -> game Y-up
    f = np.empty(len(me.loop_triangles) * 3, np.int32)
    me.loop_triangles.foreach_get("vertices", f)
    name = o.name.split(".")[0]
    while name + "__v" in arrays:
        name += "_"
    arrays[name + "__v"], arrays[name + "__f"] = v, f.reshape(-1, 3)
    print(f"[mesh] {name}: {len(v)} verts {len(f) // 3} tris")
    ev.to_mesh_clear()
np.savez_compressed(out, **arrays)
print("[ok]", out)

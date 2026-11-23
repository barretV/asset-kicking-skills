"""Rig access for any upright character rig - axes, chains and posing helpers.

Nothing in this file is specific to one character. Everything that *is* specific - where the
character faces, which bone is which, where the floor is - lives in a project's `rig.json`,
which `bin/discover_rig.py` proposes and a human confirms once.

The reason axes are configured rather than assumed: a rig can be modelled at any angle inside
its armature. This pipeline's first character sits 38 deg off the armature axes, so bone-local
Euler rotations mean nothing for authoring. Poses are therefore specified about the character's
own frame:

    LAT  the character's right       yaw   = about UP    (+ turns the right side forward)
    FWD  the facing direction        pitch = about LAT   (+ raises a forward limb)
    UP   up                          roll  = about FWD

Import inside Blender scripts:

    from rigmap import load, D
    rig = load('model.glb')          # reads model-adjacent rig.json
"""
import json
import math
import os

import bpy
from mathutils import Matrix, Quaternion, Vector

D = math.radians


def _unit(v, default):
    try:
        v = Vector(v)
        return v.normalized() if v.length > 1e-9 else Vector(default)
    except (TypeError, ValueError):
        return Vector(default)


def config_path_for(glb, explicit=None):
    """Where this model's config lives: explicit, then $RIG_JSON, then beside the model.

    A build directory usually holds many exports of one rig, so `<model>.rig.json` and a plain
    `rig.json` next to it both count - that way one config serves every build in a folder.
    """
    if explicit:
        return explicit
    if os.environ.get('RIG_JSON'):
        return os.environ['RIG_JSON']
    folder = os.path.dirname(os.path.abspath(glb))
    stem = os.path.splitext(os.path.basename(glb))[0]
    for candidate in (os.path.join(folder, stem + '.rig.json'),
                      os.path.join(folder, 'rig.json')):
        if os.path.exists(candidate):
            return candidate
    return os.path.join(folder, stem + '.rig.json')


def read_config(glb, explicit=None):
    path = config_path_for(glb, explicit)
    if not os.path.exists(path):
        raise SystemExit(
            'no rig config at %s\n'
            'Run:  blender -b -P bin/discover_rig.py -- %s\n'
            'then check the bone table it prints and save the config it writes.' % (path, glb))
    with open(path, 'r', encoding='utf-8') as fh:
        return json.load(fh), path


class Rig:
    """An armature + its skinned mesh, addressed through a rig.json."""

    def __init__(self, cfg, arm, mesh):
        self.cfg = cfg
        self.arm = arm
        self.mesh = mesh
        ax = cfg.get('axes', {})
        self.LAT = _unit(ax.get('lat'), (1, 0, 0))
        self.FWD = _unit(ax.get('fwd'), (0, 1, 0))
        self.UP = _unit(ax.get('up'), (0, 0, 1))
        ch = cfg['chains']
        self.ROOT = ch['root']
        self.SPINE = tuple(ch.get('spine', ()))
        self.HEAD = tuple(ch.get('head', ()))
        self.ARMS = {k: tuple(v) for k, v in ch.get('arms', {}).items()}
        self.LEGS = {k: tuple(v) for k, v in ch.get('legs', {}).items()}
        self.GROUND = cfg.get('ground', 0.0)
        self.fps = cfg.get('fps', 24)
        self.sides = cfg.get('sides', {'R': 'R', 'L': 'L'})

    # -- loading ------------------------------------------------------------
    @classmethod
    def load(cls, glb, cfg_path=None, keep_scene=False):
        cfg, path = read_config(glb, cfg_path)
        if not keep_scene:
            bpy.ops.object.select_all(action='SELECT')
            bpy.ops.object.delete(use_global=False)
        bpy.ops.import_scene.gltf(filepath=glb)
        arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
        mesh = max((o for o in bpy.data.objects if o.type == 'MESH'),
                   key=lambda o: len(o.data.vertices))
        bpy.context.view_layer.objects.active = arm
        bpy.context.scene.render.fps = cfg.get('fps', 24)
        rig = cls(cfg, arm, mesh)
        rig.config_path = path
        return rig

    # -- posing -------------------------------------------------------------
    def rest_q(self, name):
        return self.arm.data.bones[name].matrix_local.to_quaternion()

    def world_q(self, yaw=0.0, pitch=0.0, roll=0.0):
        q = Quaternion((1, 0, 0, 0))
        if yaw:
            q = Quaternion(self.UP, D(yaw)) @ q
        if pitch:
            q = Quaternion(self.LAT, D(pitch)) @ q
        if roll:
            q = Quaternion(self.FWD, D(roll)) @ q
        return q

    def set_bone(self, name, frame, yaw=0.0, pitch=0.0, roll=0.0, offset=None, key=True):
        pb = self.arm.pose.bones[name]
        rq = self.rest_q(name)
        pb.rotation_mode = 'QUATERNION'
        pb.rotation_quaternion = rq.inverted() @ self.world_q(yaw, pitch, roll) @ rq
        if key:
            pb.keyframe_insert('rotation_quaternion', frame=frame)
        if offset is not None:
            pb.location = rq.inverted() @ Vector(offset)
            if key:
                pb.keyframe_insert('location', frame=frame)
        return pb

    def set_bone_q(self, name, frame, q_world, key=True):
        pb = self.arm.pose.bones[name]
        rq = self.rest_q(name)
        pb.rotation_mode = 'QUATERNION'
        pb.rotation_quaternion = rq.inverted() @ q_world @ rq
        if key:
            pb.keyframe_insert('rotation_quaternion', frame=frame)
        return pb

    def sign(self, side):
        return 1.0 if side == 'R' else -1.0

    def key_arm(self, frame, side, inward=0.0, lift=0.0, elbow=0.0, elbow_side=0.0,
                twist=0.0, key=True):
        s = self.sign(side)
        sh, up, fore, hand = self.ARMS[side]
        self.set_bone(sh, frame, yaw=s * inward, pitch=lift, key=key)
        self.set_bone(up, frame, yaw=s * elbow_side, pitch=elbow * 0.35,
                      roll=s * twist, key=key)
        self.set_bone(fore, frame, pitch=elbow * 0.65, key=key)
        self.set_bone(hand, frame, key=key)

    def key_leg(self, frame, side, hip, knee, foot, toe=0.0, key=True):
        """`foot` is the absolute pedal angle: + toes up, - toes down (toe-off)."""
        b_hip, b_knee, b_ankle, b_toe = self.LEGS[side]
        ankle = max(-45.0, min(45.0, foot - hip - knee))
        self.set_bone(b_hip, frame, pitch=hip, key=key)
        self.set_bone(b_knee, frame, pitch=knee, key=key)
        self.set_bone(b_ankle, frame, pitch=ankle, key=key)
        self.set_bone(b_toe, frame, pitch=toe, key=key)

    def key_root(self, frame, bob=0.0, sway=0.0, push=0.0, yaw=0.0, pitch=0.0, roll=0.0,
                 key=True):
        self.set_bone(self.ROOT, frame, yaw=yaw, pitch=pitch, roll=roll, key=key,
                      offset=self.LAT * sway + self.UP * bob + self.FWD * push)

    def key_spine(self, frame, yaw=0.0, pitch=0.0, roll=0.0, head_pitch=0.0, head_yaw=0.0,
                  head_roll=0.0, key=True):
        for name, k in zip(self.SPINE, (0.5, 0.3, 0.2)):
            self.set_bone(name, frame, yaw=yaw * k, pitch=pitch * k, roll=roll * k, key=key)
        if self.HEAD:
            self.set_bone(self.HEAD[0], frame, pitch=head_pitch, yaw=head_yaw,
                          roll=head_roll, key=key)
            for extra in self.HEAD[1:]:
                self.set_bone(extra, frame, key=key)

    def clear_pose(self):
        for pb in self.arm.pose.bones:
            pb.rotation_mode = 'QUATERNION'
            pb.rotation_quaternion = (1, 0, 0, 0)
            pb.location = (0, 0, 0)
            pb.scale = (1, 1, 1)

    def new_action(self, name):
        if self.arm.animation_data is None:
            self.arm.animation_data_create()
        act = bpy.data.actions.new(name)
        self.arm.animation_data.action = act
        self.assign_slot(act)
        return act

    def assign_slot(self, act):
        """Blender 4.4+/5.x actions are slotted; older ones are not."""
        ad = self.arm.animation_data
        if ad is None or act is None:
            return
        ad.action = act
        if hasattr(ad, 'action_slot') and getattr(act, 'slots', None):
            ad.action_slot = act.slots[0]

    # -- measuring ----------------------------------------------------------
    def body_yaw(self):
        """Body rotation about UP relative to the armature axes, in degrees.

        A bone matrix is NOT a body frame: bone rolls are arbitrary, so root.matrix @ LAT is
        skewed and every measurement taken through it is wrong. The body is upright, so its
        frame is the fixed LAT/FWD/UP basis turned by the root's yaw alone.
        """
        pb = self.arm.pose.bones[self.ROOT]
        rel = pb.matrix.to_3x3() @ pb.bone.matrix_local.to_3x3().inverted()
        v = rel @ self.LAT
        flat = v - self.UP * v.dot(self.UP)
        if flat.length < 1e-6:
            return 0.0
        flat.normalize()
        a = math.degrees(self.LAT.angle(flat))
        return -a if self.LAT.cross(flat).dot(self.UP) < 0 else a

    def body_axes(self):
        A = Matrix.Rotation(D(self.body_yaw()), 3, self.UP)
        lat, fwd, up = A @ self.LAT, A @ self.FWD, A @ self.UP
        return Matrix(((lat.x, fwd.x, up.x),
                       (lat.y, fwd.y, up.y),
                       (lat.z, fwd.z, up.z)))

    def evaluated_points(self):
        deps = bpy.context.evaluated_depsgraph_get()
        ev = self.mesh.evaluated_get(deps)
        me = ev.to_mesh()
        mw = ev.matrix_world
        pts = [mw @ v.co for v in me.vertices]
        ev.to_mesh_clear()
        return pts

    def lowest_z(self):
        return min(p.z for p in self.evaluated_points())

    def group_index(self, names):
        wanted = set(names)
        return {g.index for g in self.mesh.vertex_groups if g.name in wanted}

    def weighted_points(self, names, threshold=0.5):
        """Evaluated points dominated by the given bones - one limb, not the whole mesh."""
        gidx = self.group_index(names)
        deps = bpy.context.evaluated_depsgraph_get()
        ev = self.mesh.evaluated_get(deps)
        me = ev.to_mesh()
        mw = ev.matrix_world
        out = [mw @ me.vertices[i].co for i in range(len(me.vertices))
               if sum(g.weight for g in me.vertices[i].groups if g.group in gidx) > threshold]
        ev.to_mesh_clear()
        return out


def fcurves_of(action):
    """All fcurves of an action, on slotted (4.4+, 5.x) and legacy actions."""
    try:
        return list(action.fcurves)
    except AttributeError:
        out = []
        for layer in action.layers:
            for strip in layer.strips:
                for slot in action.slots:
                    bag = strip.channelbag(slot)
                    if bag is not None:
                        out.extend(bag.fcurves)
        return out


def has_bones(action):
    return any(fc.data_path.startswith('pose.bones') for fc in fcurves_of(action))


def clip_range(action):
    f0, f1 = (int(round(v)) for v in action.frame_range)
    return f0, f1


def load(glb, cfg_path=None):
    return Rig.load(glb, cfg_path)

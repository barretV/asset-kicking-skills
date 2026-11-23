---
name: blender-anim
description: End-to-end 3D character pipeline from the command line — rig a bare generated mesh with SkinTokens in ComfyUI, retarget existing clips onto a new body, author walk/idle/punch/attack clips with Blender, verify them with measurements (loop seams, left/right symmetry, foot locking), and preview in a Three.js page. Use for animation work, rigging, resculpts that need the old animations moved over, or debugging limb/shoulder/loop artifacts.
metadata:
  category: gamedev
  tools: blender, comfyui
---

# 3D character pipeline: generate → rig → animate → retarget → verify → preview

A command-line pipeline for taking a character from "a mesh some generator gave me" to
"four clips playing in a browser", with measurements instead of eyeballing.

Two facts shape everything here:

1. **A generated mesh has no bones.** Rigging it by hand — or with a distance formula — is
   where the classic artifacts come from (a plate cracking off a belly, an arm dragging a
   strip of chest). A *learned* skinning model solves it. That is what stage 2 is for.
2. **Bone names are not trustworthy.** A learned rigger has been observed calling a 4-bone
   tail `RightUpLeg → RightLeg → RightFoot → RightToeBase` and leaving the second leg
   generic. Every stage below keys off measured geometry or a `rig.json`, never off a name.

## GPU safety (read before any GPU job)
Small and laptop GPUs can hang or hard-reboot when GPU work stacks up (the 6 GB reference laptop did), which kills every running session. GPU jobs include MOSS/ComfyUI generation, Blender renders and bakes, headed or headless browser runs (Playwright tests, playchecks, captures), benchmarks, and Unreal/Godot editor or PIE.
- **One GPU job machine-wide.** Before starting one, check that nothing else is using the GPU: `nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv`, plus running ComfyUI (`main.py`), Blender, Playwright/Chrome and other agents' sessions. If something is running, wait for it to finish. Never start a second job alongside it.
- **Cool down.** Leave about 60 s between heavy GPU jobs. Split long runs into chunks (one batch or one level at a time), not back to back.
- **Clean up.** Stop whatever you started (ComfyUI, dev servers, browsers) as soon as you are done with it.
- **Pass it on.** When you brief a subagent or a parallel session that will use the GPU, include this rule.

## Reference first, then model to it

Never model a character or creature from a text description alone. Make a reference, model to it, and judge the model against it.

1. **Make the reference.** Generate a concept with MOSS through `art-forge-loop`, in illustration mode: 2–3 seeds each of a side view and a 3/4 view, in the project's art style.
   - Start img2img from a render of the current model at denoise ~0.8 when there is one; it keeps the scale and pose. Otherwise use txt2img.
   - In the prompt, name the identity features and the 3-colour palette.
   - Keep one pick per view (≥ 9 on the project's bar) beside the model's review sheets, for example `refs/<name>-concept-side.png`.
2. **Turn it into a spec before modelling.** Write down the proportions (head : body : limbs, where the mass sits, hump or crest height), the silhouette features, and which colour goes where. Put it in the build script's header comment.
   - **Optional, for bulky creatures: a sculpt donor.** Turn the concept into a 3D sculpt with TRELLIS.2 + Hi3D in ComfyUI (the `concept-to-3d` skill). Then measure your model against it on the CPU with that skill's `hi3d_export_mesh.py`, `hi3d_compare.py` (silhouette IoU per view plus an overlay) and `hi3d_measure.py` (head, limb, hump and tail sizes).
     - Write the numbers into the spec.
     - Recipe, timings and licence: the `concept-to-3d` skill.
     - The sculpt is a measuring stick, never the shipped mesh.
     - Prefer the **side** concept: a 3/4 painting's foreshortened near limbs come out far too wide.
3. **Model** in Blender to that spec.
4. **Judge against the reference, and loop.**
   - Render the model from the same views, in the game's real shader if a preview page exists. Blender's sheet lighting and the first clip frame mislead.
   - Put the render next to the concept and list every difference that matters: silhouette, proportions, value groups, glow placement.
   - Fix the biggest difference, re-render, and repeat. Stop when a reviewer would call it the concept in 3D, or when the gaps left are deliberate (game readability beats the painting).
5. **Keep the evidence:** the concept plus the before and after sheets, and record the score.

MOSS is a GPU job: follow GPU safety, and stop ComfyUI before rendering.

## Prerequisites

| need | why | check |
| --- | --- | --- |
| Blender 4.4+ (5.x fine) | all authoring, verification, rendering | `blender --version` |
| ComfyUI + `ComfyUI-SkinTokens` | stage 2, learned rigging | `curl -s localhost:8188/system_stats` |
| SkinTokens weights (~1.6 GB) | `articulation_xl_quantization_256_token_4/grpo_1400.ckpt` + `skin_vae_2_10_32768/last.ckpt` under `ComfyUI/models/skintoken/` | `ls ComfyUI/models/skintoken` |
| GPU with ~6 GB VRAM | rigging fits in 6 GB with ComfyUI started `--novram` (the `run_asset_kit_rigging` launcher); upstream asks for 14 GB without offloading | `nvidia-smi` |

Stages 3–7 need only Blender. Skip stage 2 entirely if your model already has a rig.

Always run scripts headless with `--python-exit-code 1`:

```bash
blender -b --python-exit-code 1 -P <script> -- <args>
```

Without that flag Blender exits 0 on a Python exception and a broken build looks like success.

## Stage 1 — what you start with

A generated `.glb`/`.fbx` is usually one mesh, no armature, no vertex groups. Confirm:

```bash
blender -b --python-exit-code 1 -P bin/audit_rig.py -- model.glb
```

`no armature in model.glb -- the mesh is not rigged` means go to stage 2.

## Stage 2 — rig it (learned, not hand-painted)

```bash
cd ComfyUI && venv/Scripts/python.exe main.py --novram &      # leave it running
python bin/rig_skintokens.py --mesh model.glb --copy-to model_rigged.glb
```

~70 s for a 120k-vertex mesh. The graph is `assets/rigging_workflow.json`; only the mesh
path is rewritten. Output lands in `ComfyUI/output/`.

Then **audit before you trust it**:

```bash
blender -b --python-exit-code 1 -P bin/audit_rig.py -- model_rigged.glb --png rig.png
```

Read the centroid column. A chain whose centroids march away from the body over ~1 body
length is a tail; a limb you expected to own half the mesh and owns 2% is a bad bind.
Compare `influences/vert` (~3.7 is healthy) and `near-rigid` between two rigs — a rig at
0 % near-rigid on a low-poly mesh is usually over-smoothed.

## Stage 3 — discover the character's frame

Every rig is modelled at some arbitrary angle inside its armature, so a character's own
axes must be measured, not assumed:

```bash
blender -b --python-exit-code 1 -P bin/discover_rig.py -- model.glb [--flip-sides]
```

Writes `model.rig.json` (axes, chains, ground, fps) next to the model and prints the table
it inferred. **That config is the per-character knowledge — commit it.**

* The frame comes from the plane the mesh mirrors onto itself about. A clear best plane
  with a large gap to the runner-up is a good sign; "no clear symmetry plane" means the
  mesh is asymmetric and you should set `axes` by hand.
* Left/right is decided from `.L`/`.R` **and** spelled-out `Left*`/`Right*` bone names when
  present. When they are absent it is a coin flip — if sides come out swapped, re-run with
  `--flip-sides` (it negates `lat`/`fwd` *and* swaps the R/L chain labels; editing `axes.lat`
  alone leaves mislabelled chains behind).

## Stage 4 — author clips, or move existing ones onto a new body

**Authoring** uses `lib/rigmap.py`, which poses bones about the character's axes rather
than bone-local ones:

```python
import sys; sys.path.insert(0, 'lib')
from rigmap import Rig
rig = Rig.load('model.glb')
act = rig.new_action('Idle')
rig.key_spine(frame, yaw=2.4, pitch=-1.4, head_pitch=2.4)
rig.key_arm(frame, 'R', lift=12, elbow=18)
rig.key_leg(frame, 'R', hip=8, knee=-12, foot=2)
rig.key_root(frame, bob=0.01, sway=0.005)
```

Degrees, family-friendly names (`lift`, `elbow`, `hip`, `knee`, `foot`), so a pose reads as
a pose.

**Retargeting** is for "the motion is good, the body changed" — a resculpt, new
proportions, a fresh rig. Re-authoring throws away the timing that made the clips work:

```bash
blender -b --python-exit-code 1 -P bin/retarget_clips.py -- \
    old_animated.glb new_rigged.glb out.glb --renders renders/rt
```

It maps chains from the two `rig.json` files (no bone names), folds a longer limb onto a
shorter one by giving the last target bone the deepest source bone, moves the target into
the source's world frame, transfers world-space rotation deltas against a stance reference
(`--ref`, default `Idle`), then foot-locks every frame. It prints the local motion each
folded bone carried: ~0° means the fold is lossless; a large value means real motion is
being dropped.

## Stage 5 — verify (this is the gate)

```bash
blender -b --python-exit-code 1 -P bin/verify.py -- model.glb \
    --loop Walk,Idle --phase Walk=12,Punch=-16
```

Per clip: loop seam (mm), left/right mirror (mm), lowest vertex vs floor, weight-sum check.
Exits non-zero on failure, so it can gate a rebuild. `--phase` is not a fudge factor: a
walk is a cross-body gait, so the left arm follows the right half a cycle later; without
the offset every correct walk reports as broken.

## Stage 6 — see it

```bash
blender -b --python-exit-code 1 -P bin/render_ab.py -- \
    model.glb Idle 3q renders/idle_3q.png 1 19 37
```

Views: `front back side 3qm 3q top`. `3qm` is the mirror of `3q` about the sagittal plane,
so a true mirror seen from the mirrored camera must produce the same picture — the cheapest
proof that a mirror really mirrors.

Motion is what you usually need though. For "does it play", copy the viewer pattern from a
`preview/index.html` (loads a GLB, one button per clip, scrubs, exposes
`window.__dbg = {scene, camera, model, mixer}`), serve it, and read the clip time twice:

```bash
cd preview && python -m http.server 8095
```

Reading `__dbg` or the status line at two different times is the only way to tell a playing
clip from a frozen one.

## Variant — sculpt as the model (Hi3D → clean/decimate → toon zones → rig → verify)

When a Hi3D or TRELLIS sculpt is good enough to ship, skip the procedural build:
1. Clean it: remesh, drop floaters, symmetrize, floor.
2. Decide the colour zones on the full-res mesh, from a registered concept plus geometry: ray thickness for claws and teeth, openness for the mouth.
3. Decimate with zone borders protected, then give each low face the majority zone of the nearest hi-res faces and merge islands.
4. Rig it with capsule-distance weights, author clips with floor IK, and gate with `verify.py`.

Toon rules learned the hard way:
- One solid colour per face per region.
- Smooth the *shading normals*, not the colours: Taubin-smoothed custom normals.
- Keep neighbouring tones close.
- Glow lines only on long chains.

Hybrid variant (keep the sculpt's body, rebuild the face, plates, claws and crystals as clean procedural parts; plates as Voronoi slabs over a glowing under-layer; a toe clamp for long claws): see the `concept-to-3d` skill, step 3b.

verify.py imports at 24 fps, so give `--phase` in 24 fps frames.

## Traps (each one cost a pass on a real character)

1. **A bone matrix is not a body frame.** Bone rolls are arbitrary, so `root.matrix @ LAT`
   is skewed. Use `Rig.body_axes()` (root yaw applied to the configured basis).
2. **Mirroring a rotation is not reflecting three columns** — that gives det = −1 and the
   export splits it into a rotation plus negative scale. Conjugate: `S @ R @ S`, and reflect
   the joint's translation too, or the mirrored pose hangs off the un-mirrored skeleton.
3. **glTF bakes a key on every frame.** Sparse keys leave the previous pose showing between
   them.
4. **Key before the next depsgraph update**, or the re-evaluation discards an unkeyed pose.
5. **A loop must be written through its last frame**, repeating the first. Skipping it put a
   355 mm hitch in a walk that otherwise looked fine.
6. **Never project one limb's vertices onto another limb's surface.** Nearest-point
   projection pulls a limb's inside onto the outside — the arm collapses into a fin pressed
   into the belly.
7. **Skin weights must sum to 1: replace, never add.** Adding mirrored weights without
   clearing the old groups doubles the transform; that reads as "the arm melted".
8. **Check weights in a POSED frame.** At rest the armature is a no-op, so weight errors are
   invisible.
9. **Shape keys own the geometry.** Write shape-key blocks (including Basis) too, or the
   export silently drops your vertex edits.
10. **One Blender process per file.** Importing a second GLB in one session renames actions
    (`Punch.001`); a lookup by name then compares a file with itself.
11. **`polygon.hide` is viewport-only.** It does not affect a render: a "render without the
    arms" test came out pixel-identical to the full one. Delete faces with `bmesh` when you
    need to test a hypothesis.
12. **Blender resolves a relative `scene.render.filepath` outside the project** (frames
    landed in `C:\renders\`). `os.path.abspath` every output directory.
13. **Piping Blender through `head` sends SIGPIPE** and can kill it before it writes the
    GLB, leaving a stale file. Redirect to a log, then grep the log.
14. **A retarget needs a stance reference.** Measure deltas against one clip's first frame
    (`Idle`), never against the rest pose — the rest pose is a T-pose-ish modelling stance,
    so every clip inherits a constant lean.
15. **Don't conjugate deltas between two character frames if you can move the rig instead.**
    Conjugating is equivalent in theory and was measurably not: Idle transferred within 17°
    but walk/punch diverged past 100°. Physically rotating the target into the source's
    frame reproduced the verified result to 0.6° on the root.
16. **After moving a rig into another frame, its `rig.json` axes are stale.** Cameras built
    from them film the character from behind. Use the source's axes.
17. **Unparenting a mesh to apply transforms and not re-parenting** makes the glTF exporter
    warn "Armature must be the parent of skinned mesh". Set `mesh.parent = arm` afterwards.
18. **A Hi3D sculpt has no scale or floor.**
    - Hi3D normalizes its output to unit radius. Scale it to the model's length, with its lowest point on the model's floor, before comparing (`hi3d_compare.py` does this).
    - A raw 1024 sculpt is 2–4M faces. Decimate it on import (`--max-faces`) or Blender and Pillow crawl.
19. **Thicker limbs push verify's `ground` numbers down.** A wrist ball of radius r on a joint at height h pokes below the floor once r > h.
    - Widen a stance with the paw pads, not the wrist.
    - Re-run `verify.py` against the old numbers: the clips are the same, so any change in "through the floor" comes from the geometry.

## Files

| path | what it is |
| --- | --- |
| `lib/rigmap.py` | rig loading, per-character axes/chains, posing helpers, measurement |
| `bin/rig_skintokens.py` | stage 2: drive SkinTokens in ComfyUI to rig a bare mesh |
| `bin/audit_rig.py` | what each bone actually owns (the names lie); weight-quality numbers |
| `bin/discover_rig.py` | propose `model.rig.json` (axes, chains, floor, fps); `--flip-sides` |
| `bin/retarget_clips.py` | move clips between rigs, fold longer limbs, foot-lock |
| `bin/verify.py` | weights, loop seams, L/R mirror, floor — exits non-zero on failure |
| `bin/render_ab.py` | tiled A/B renders from one fixed camera |
| `bin/mirror_clips.py` | mirror one side's motion onto the other, with loop/phase handling |
| `assets/rigging_workflow.json` | the SkinTokens ComfyUI graph template |
| `install.py` | copy this skill into another repository |

## Using it in another repo

```bash
python skills/blender-anim/install.py --into ../other-game            # -> other-game/.agents/skills/blender-anim
python skills/blender-anim/install.py --into ../other-game --claude   # -> .claude/skills/blender-anim
python skills/blender-anim/install.py --into ~/.agents                # global: every project
```

`skills` is discovered only under `.agents/skills/` or `.claude/skills/` (project), or
`~/.agents/skills/` (global). A copy sitting in a plain `skills/` folder is **not loaded** —
that is the difference between a skill that works and one that silently never appears.

Then, in that repo: run `discover_rig.py` on its character once and commit the
`*.rig.json` beside the model. That config is the asset's documentation and it is what
makes every other script work without edits.

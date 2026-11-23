"""Rig a bare mesh -- no skeleton -- by driving SkinTokens in ComfyUI.

    python bin/rig_skintokens.py --mesh char.glb [--workflow assets/rigging_workflow.json]
                                [--server http://127.0.0.1:8188] [--copy-to out.glb]

Most 3D generators hand you a **mesh with no bones and no vertex groups**. Painting
weights by hand (or with an inverse-distance formula) is the usual next step, and it is
the step that produces the classic artifacts: a belly plate that cracks open, an arm
that drags a strip of chest, a shoulder that tears. A learned skinning model solves those
because it was trained on skinned meshes; a distance function has no idea a plate lies
on top of a belly.

SkinTokens (the node in `custom_nodes/ComfyUI-SkinTokens`) does that solve, using a
headless Blender for import/export. It takes ~70 s for a 120k-vert mesh.

Prerequisites (see the skill's SKILL.md for the full setup)
----------------------------------------------------------
* ComfyUI running: `venv\\Scripts\\python.exe main.py --novram` at ``--server``.
* `ComfyUI-SkinTokens` in `custom_nodes/`.
* Weights under `ComfyUI/models/skintoken/`: `articulation_xl_quantization_256_token_4/grpo_1400.ckpt`
  (~1.1 GB) and `skin_vae_2_10_32768/last.ckpt` (~465 MB).

Output lands in `ComfyUI/output/`; `--copy-to` puts it where you want it.

Then check the rig before you animate it: `bin/audit_rig.py`. **Bone names are not
trustworthy** -- this model has been observed naming a 4-bone tail `RightUpLeg .. RightToeBase`
and leaving the second leg generic. Audit ownership, never names.
"""
import argparse
import json
import os
import shutil
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)


def post(server, path, payload):
    req = urllib.request.Request(server + path, data=json.dumps(payload).encode(),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def get(server, path):
    with urllib.request.urlopen(server + path, timeout=30) as r:
        return json.loads(r.read().decode())


def wait_up(server, timeout=180):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            get(server, '/system_stats')
            return True
        except Exception:
            time.sleep(2)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mesh', required=True)
    ap.add_argument('--workflow', default=os.path.join(SKILL, 'assets', 'rigging_workflow.json'))
    ap.add_argument('--server', default='http://127.0.0.1:8188')
    ap.add_argument('--copy-to', help='copy the resulting GLB here')
    ap.add_argument('--comfy-output', help='ComfyUI output dir (default: inferred from --server)')
    a = ap.parse_args()

    mesh = os.path.abspath(a.mesh)
    if not os.path.isfile(mesh):
        sys.exit('mesh not found: %s' % mesh)
    with open(a.workflow) as fh:
        wf = json.load(fh)

    loader = next((n for n in wf.values()
                   if n.get('class_type') == 'SkinTokensLoadMesh'), None)
    if loader is None:
        sys.exit('workflow has no SkinTokensLoadMesh node')
    loader['inputs']['mesh_path'] = mesh.replace('\\', '/')
    print('mesh      : %s' % loader['inputs']['mesh_path'])
    for n in wf.values():
        if n.get('class_type') == 'SkinTokensModelLoader':
            print('checkpoint: %s' % n['inputs'].get('model_name'))

    if not wait_up(a.server):
        sys.exit('ComfyUI is not answering on %s\n'
                 'start it with:  python main.py --novram' % a.server)

    pid = post(a.server, '/prompt', {'prompt': wf})['prompt_id']
    print('queued    : %s' % pid, flush=True)

    t0 = time.time()
    while True:
        time.sleep(5)
        h = get(a.server, '/history/%s' % pid)
        if pid not in h:
            continue
        entry = h[pid]
        status = entry.get('status', {})
        print('status    : %s  (%.1f s)' % (status.get('status_str'), time.time() - t0))
        for msg in status.get('messages', []):
            if msg[0] in ('execution_error', 'execution_interrupted'):
                print(json.dumps(msg[1])[:2000])
        produced = []
        for node_id, out in entry.get('outputs', {}).items():
            for _k, val in out.items():
                if not isinstance(val, list):
                    continue
                for item in val:
                    if isinstance(item, str):
                        produced.append(item)
                    elif isinstance(item, dict):
                        for key in ('filename', 'path', 'mesh_path'):
                            if key in item:
                                produced.append(str(item[key]))
        if not produced:
            sys.exit('the graph ran but reported no output file; check the ComfyUI log')
        for p in produced:
            print('output    : %s' % p)
        name = os.path.basename(produced[-1].split('?')[0])
        if a.copy_to:
            outdir = a.comfy_output or _infer_output_dir()
            src = os.path.join(outdir, name)
            if not os.path.isfile(src):
                sys.exit('expected %s but it is not there; pass --comfy-output' % src)
            shutil.copy2(src, os.path.abspath(a.copy_to))
            print('copied    : %s' % os.path.abspath(a.copy_to))
            print('\nnext: audit the rig before animating it --')
            print('  blender -b --python-exit-code 1 -P %s/bin/audit_rig.py -- %s'
                  % (os.path.basename(SKILL), os.path.abspath(a.copy_to)))
        return


def _infer_output_dir():
    """ComfyUI/output, found from this skill's usual place beside the ComfyUI folder."""
    guess = os.path.abspath(os.path.join(SKILL, '..', '..', 'ComfyUI', 'output'))
    return guess


if __name__ == '__main__':
    main()

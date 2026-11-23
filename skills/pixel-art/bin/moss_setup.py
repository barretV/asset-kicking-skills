"""Download the MOSS-Image Turbo + moss-pixelart LoRA stack for a 6 GB GPU.

Files (~13.2 GB total), all public, all in ComfyUI's native formats:
  diffusion_models/moss_image_sft_turbo_int8_convrot.safetensors  5.41 GB
  text_encoders/qwen3.5_9b_w4a8_gptq.safetensors                  7.34 GB
  vae/flux2-vae_small.safetensors                                 0.25 GB
  loras/moss-pixelart-v.0.3.safetensors                           0.15 GB

Why these variants:
  * turbo INT8 ConvRot is the 8-step distillation in ComfyUI's native quant
    format, half the size of bf16 and the only one that fits 6 GB comfortably;
  * w4a8 GPTQ is the 4-bit text encoder ComfyUI's own MOSS template recommends
    (bf16 is 19.3 GB, int8 9.75 GB);
  * flux2-vae_small decodes in less VRAM than the full FLUX.2 VAE.

Usage:
  python moss_setup.py                 # download into ComfyUI/models
  python moss_setup.py --check         # only verify, no network
  python moss_setup.py --comfy D:\\ComfyUI
"""
import argparse
import os
import sys


def comfy_dir():
    """ComfyUI root: $COMFYUI_DIR, else `comfyui_dir` in the asset-kicking-skills config
    (~/.asset-kicking-skills/config.json, or $ASSET_KIT_CONFIG), written by setup/detect.py."""
    if os.environ.get("COMFYUI_DIR"):
        return os.environ["COMFYUI_DIR"]
    cfg = os.environ.get("ASSET_KIT_CONFIG") or os.path.join(
        os.path.expanduser("~"), ".asset-kicking-skills", "config.json")
    try:
        with open(cfg, encoding="utf-8") as fh:
            path = __import__("json").load(fh).get("comfyui_dir")
        if path:
            return path
    except (OSError, ValueError):
        pass
    raise SystemExit("ComfyUI folder unknown: set COMFYUI_DIR or run setup/detect.py --comfyui <path>")


FILES = [
    ("toxicdog/MOSS-Image-SFT-Turbo-INT8-ConvRot",
     "diffusion_models/moss_image_sft_turbo_int8_convrot.safetensors"),
    ("Comfy-Org/MOSS-Image",
     "text_encoders/qwen3.5_9b_w4a8_gptq.safetensors"),
    ("Comfy-Org/MOSS-Image",
     "vae/flux2-vae_small.safetensors"),
    ("ProbablyHumanAB/moss-pixelart-v.0.3",
     "moss-pixelart-v.0.3.safetensors"),
]

DEFAULT_COMFY = None  # resolved by comfy_dir() when --comfy is not given


def destinations(comfy):
    for repo, remote in FILES:
        sub = "loras" if repo.endswith("moss-pixelart-v.0.3") else os.path.dirname(remote)
        yield repo, remote, os.path.join(comfy, "models", sub, os.path.basename(remote))


def check(comfy):
    ok = True
    for repo, remote, dest in destinations(comfy):
        if os.path.exists(dest) and os.path.getsize(dest) > 1024 * 1024:
            print(f"OK    {os.path.relpath(dest, comfy)}  ({os.path.getsize(dest)/1e9:.2f} GB)")
        else:
            print(f"MISS  {os.path.relpath(dest, comfy)}  <- {repo}/{remote}")
            ok = False
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--comfy", default=DEFAULT_COMFY, help="ComfyUI root folder (default: $COMFYUI_DIR or the setup config)")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    args.comfy = args.comfy or comfy_dir()

    if args.check:
        raise SystemExit(0 if check(args.comfy) else 1)

    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        raise SystemExit("huggingface_hub missing: run ComfyUI's venv python, or pip install huggingface_hub")

    models = os.path.join(args.comfy, "models")
    for repo, remote, dest in destinations(args.comfy):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.exists(dest) and os.path.getsize(dest) > 1024 * 1024:
            print(f"SKIP  {os.path.basename(dest)}")
            continue
        print(f"\n==> {repo}/{remote}", flush=True)
        hf_hub_download(repo_id=repo, filename=remote, local_dir=models)
        produced = os.path.join(models, remote.replace("/", os.sep))
        if produced != dest and os.path.exists(produced):
            os.replace(produced, dest)
        if not os.path.exists(dest):
            raise SystemExit(f"download finished but {dest} is missing")
        print(f"    {os.path.getsize(dest)/1e9:.2f} GB", flush=True)

    print("\nAll model files present.")
    sys.exit(0)


if __name__ == "__main__":
    main()

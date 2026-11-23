"""Generate pixel-art source images with MOSS-Image Turbo + the moss-pixelart LoRA.

This is the "AI source" stage of the pixel-art pipeline: it produces an
8x-scaled pixel-art image (one logical pixel = 8x8 output pixels) on a flat
background. `moss_snap.py` then cuts the background and downsamples it to the
native logical resolution.

Why this model instead of SD 1.5 + a style LoRA:
  * the LoRA was trained on 64x64 sprites upscaled 8x, so the grid is real,
    not a post-process approximation;
  * MOSS-Image is a 5B flow-matching DiT and runs in ~6 GB with INT8 ConvRot
    weights + a 4-bit text encoder;
  * the 8:1 output means the downsample is a clean BOX average, with no
    invented pixels in between.

Requires ComfyUI (MOSS-Image nodes are native since Oct 2026) and the model
files listed in `moss_setup.py`. Queue through the HTTP API - no custom nodes.

Examples:
  python moss_generate.py --check
  python moss_generate.py --prompt "pxl8x, pixel art sprite of a chibi axolotl knight ..."
  python moss_generate.py --preset idle --count 4 --size 512
  python moss_generate.py --preset idle --count 2 --size 1024 --seed 100
  # upgrade an existing sprite instead of inventing one (see --init)
  python moss_generate.py --init item.png --denoise 0.55 --prefix upgrade

img2img (--init): the source sprite is placed on the same 8:1 grid the LoRA was trained
on and used as the sampler's latent, so the model REFINES that design rather than drawing
a new one. This is the path for "same weapon, better pixels" work: text-to-image always
reinvents, img2img keeps the silhouette and layout.
"""
import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import uuid


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


HERE = os.path.dirname(os.path.abspath(__file__))
ASSET = os.path.join(os.path.dirname(HERE), "assets", "moss_pixelart_api.json")

DEFAULT_SERVER = "http://127.0.0.1:8188"

UNET = "moss_image_sft_turbo_int8_convrot.safetensors"
CLIP = "qwen3.5_9b_w4a8_gptq.safetensors"
VAE = "flux2-vae_small.safetensors"
LORA = "moss-pixelart-v.0.3.safetensors"

PRESETS = {
    "idle": ("pxl8x, pixel art sprite of a chibi axolotl knight, coral pink axolotl "
             "with feathery pink gills, small silver knight helmet with a teal plume, "
             "silver chestplate, short sword held low, standing idle, front three-quarter "
             "view, flat lavender background, limited palette, crisp pixel art, centered"),
    "run": ("pxl8x, pixel art sprite of a chibi axolotl knight, coral pink axolotl with "
            "feathery pink gills, small silver knight helmet with a teal plume, silver "
            "chestplate, short sword, running to the right, side view, legs apart mid "
            "stride, flat lavender background, limited palette, crisp pixel art, centered"),
    "slash": ("pxl8x, pixel art sprite of a chibi axolotl knight, coral pink axolotl with "
              "feathery pink gills, small silver knight helmet with a teal plume, silver "
              "chestplate, swinging a short sword in a wide forward slash, white motion "
              "arc, side view, flat lavender background, limited palette, crisp pixel art, centered"),
}


# --------------------------------------------------------------------------- #
# graph
# --------------------------------------------------------------------------- #
def build_graph(prompt, width, height, seed, steps, cfg, lora_strength, prefix,
                negative=""):
    """Minimal MOSS-Image Turbo graph (no custom nodes, no SLG for turbo)."""
    return {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": UNET, "weight_dtype": "default"}},
        "2": {"class_type": "LoraLoaderModelOnly",
              "inputs": {"model": ["1", 0], "lora_name": LORA,
                         "strength_model": lora_strength}},
        "3": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": CLIP, "type": "moss_image", "device": "default"}},
        "4": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt, "clip": ["3", 0]}},
        "5": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative, "clip": ["3", 0]}},
        "6": {"class_type": "EmptyFlux2LatentImage",
              "inputs": {"width": width, "height": height, "batch_size": 1}},
        "7": {"class_type": "KSampler",
              "inputs": {"model": ["2", 0], "seed": seed, "steps": steps,
                         "cfg": cfg, "sampler_name": "euler", "scheduler": "simple",
                         "positive": ["4", 0], "negative": ["5", 0],
                         "latent_image": ["6", 0], "denoise": 1.0}},
        "8": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "9": {"class_type": "VAEDecode",
              "inputs": {"samples": ["7", 0], "vae": ["8", 0]}},
        "10": {"class_type": "SaveImage",
               "inputs": {"images": ["9", 0], "filename_prefix": prefix}},
    }


def prepare_init(src_path, size, scale, bg=(208, 200, 216)):
    """Put an existing sprite on the 8:1 grid, centred on the flat background MOSS expects.

    `scale` is output pixels per source pixel. Keep it a multiple of 8 so the init stays
    grid-aligned (16 = each source pixel becomes 2 logical pixels at the 8:1 snap).
    """
    from PIL import Image

    im = Image.open(src_path).convert("RGBA")
    big = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
    if big.width > size or big.height > size:
        raise SystemExit("init too large: %dx%d in a %d canvas (lower --init-scale)"
                         % (big.width, big.height, size))
    canvas = Image.new("RGBA", (size, size), tuple(bg) + (255,))
    canvas.alpha_composite(big, ((size - big.width) // 2, (size - big.height) // 2))
    return canvas.convert("RGB")


def build_img2img_graph(prompt, width, height, seed, steps, cfg, lora_strength, prefix,
                        init_name, denoise, negative=""):
    """Same stack as build_graph, but the latent comes from the init image."""
    g = build_graph(prompt, width, height, seed, steps, cfg, lora_strength, prefix, negative)
    del g["6"]                                    # no empty latent: we encode the source
    g["11"] = {"class_type": "LoadImage", "inputs": {"image": init_name}}
    g["12"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["11", 0], "vae": ["8", 0]}}
    g["7"]["inputs"]["latent_image"] = ["12", 0]
    g["7"]["inputs"]["denoise"] = denoise
    return g


def comfy_input_dir():
    comfy = comfy_dir()
    return os.path.join(comfy, "input")


# --------------------------------------------------------------------------- #
# http
# --------------------------------------------------------------------------- #
def _post(server, path, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(server + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def _get(server, path):
    with urllib.request.urlopen(server + path, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def wait_for_server(server, timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            _get(server, "/system_stats")
            return True
        except Exception:
            time.sleep(3)
    return False


def generate_one(server, prompt, width, height, seed, steps, cfg, lora,
                 negative, out_dir, prefix, init_name=None, denoise=1.0):
    if init_name:
        graph = build_img2img_graph(prompt, width, height, seed, steps, cfg, lora,
                                    prefix, init_name, denoise, negative)
    else:
        graph = build_graph(prompt, width, height, seed, steps, cfg, lora,
                            prefix, negative)
    body = {"prompt": graph, "client_id": uuid.uuid4().hex}
    pid = _post(server, "/prompt", body)["prompt_id"]
    print(f"  queued {pid[:8]}  seed={seed}  {width}x{height}", flush=True)
    t0 = time.time()
    while True:
        time.sleep(2)
        hist = _get(server, f"/history/{pid}")
        if pid not in hist:
            if time.time() - t0 > 1800:
                raise TimeoutError("generation exceeded 30 min")
            continue
        entry = hist[pid]
        status = entry.get("status", {})
        if status.get("status_str") == "error":
            raise RuntimeError(json.dumps(status)[:1200])
        saved = []
        for node in entry.get("outputs", {}).values():
            for img in node.get("images", []):
                q = urllib.parse.urlencode({"filename": img["filename"],
                                            "subfolder": img.get("subfolder", ""),
                                            "type": img.get("type", "output")})
                with urllib.request.urlopen(f"{server}/view?{q}", timeout=300) as r:
                    data = r.read()
                dest = os.path.join(out_dir, f"seed_{seed:05d}_{img['filename']}")
                with open(dest, "wb") as f:
                    f.write(data)
                saved.append(dest)
        print(f"  done in {time.time()-t0:.1f}s -> {', '.join(saved)}", flush=True)
        return saved


# --------------------------------------------------------------------------- #
# cli
# --------------------------------------------------------------------------- #
def check_models():
    comfy = comfy_dir()
    expect = [(UNET, "diffusion_models"), (CLIP, "text_encoders"),
              (VAE, "vae"), (LORA, "loras")]
    ok = True
    for name, sub in expect:
        path = os.path.join(comfy, "models", sub, name)
        if os.path.exists(path):
            print(f"OK    {sub}/{name}  ({os.path.getsize(path)/1e9:.2f} GB)")
        else:
            print(f"MISS  {sub}/{name}  -> python moss_setup.py")
            ok = False
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="verify model files and exit")
    ap.add_argument("--server", default=DEFAULT_SERVER)
    ap.add_argument("--prompt", default=None)
    ap.add_argument("--preset", choices=sorted(PRESETS), default=None)
    ap.add_argument("--negative", default="", help="empty for the turbo model")
    ap.add_argument("--size", type=int, default=512, help="square size (512/768/1024)")
    ap.add_argument("--width", type=int, default=None)
    ap.add_argument("--height", type=int, default=None)
    ap.add_argument("--steps", type=int, default=8)
    ap.add_argument("--cfg", type=float, default=1.0)
    ap.add_argument("--lora", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=777)
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--out", default=os.path.join(os.getcwd(), "raw"))
    ap.add_argument("--prefix", default="moss_pxl/sprite")
    ap.add_argument("--init", default=None,
                    help="img2img source sprite to upgrade instead of inventing one")
    ap.add_argument("--denoise", type=float, default=0.55,
                    help="img2img strength: 0.35 keeps the design tightly, 0.7+ starts redrawing")
    ap.add_argument("--init-scale", type=int, default=16,
                    help="output px per source px in the init image (multiple of 8 keeps the grid)")
    args = ap.parse_args()

    if args.check:
        raise SystemExit(0 if check_models() else 1)

    prompt = args.prompt or (PRESETS[args.preset] if args.preset else PRESETS["idle"])
    if "pxl8x" not in prompt.lower():
        print("WARNING: the moss-pixelart LoRA needs the 'pxl8x' trigger first", flush=True)
    width = args.width or args.size
    height = args.height or args.size
    if width % 16 or height % 16:
        raise SystemExit("width/height must be multiples of 16 (use multiples of 64)")

    os.makedirs(args.out, exist_ok=True)
    if not wait_for_server(args.server):
        raise SystemExit(f"ComfyUI is not answering on {args.server} - start ComfyUI with the run_asset_kit launcher (setup/launcher.py)")
    if not check_models():
        raise SystemExit("model stack incomplete")

    init_name = None
    if args.init:
        if args.init_scale % 8:
            print("WARNING: --init-scale should be a multiple of 8 to stay on the 8:1 grid", flush=True)
        page = prepare_init(args.init, width, args.init_scale)
        dest = comfy_input_dir()
        os.makedirs(dest, exist_ok=True)
        safe = args.prefix.replace("/", "_").replace("\\", "_")
        init_name = "moss_init_%s_%s.png" % (safe, uuid.uuid4().hex[:6])
        page.save(os.path.join(dest, init_name))
        print("init: %s -> %s (%dx%d)" % (args.init, init_name, page.width, page.height), flush=True)

    for i in range(args.count):
        generate_one(args.server, prompt, width, height, args.seed + i,
                     args.steps, args.cfg, args.lora, args.negative,
                     args.out, args.prefix, init_name, args.denoise)


if __name__ == "__main__":
    main()

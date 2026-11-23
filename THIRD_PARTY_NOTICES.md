# Third-party material included in this repo

Everything else in this repo is MIT under [LICENSE](LICENSE). The items below were written by others and keep their own licences. Third-party software and model weights that the setup downloads are **not** included; see [LICENSES.md](LICENSES.md).

## Pixel-art craft rules

- **Files:** `skills/pixel-art/knowledge/rules/*.md`
- **Source:** https://github.com/with-pebbly/aseprite-ai-artist (`rules/`)
- **Licence:** MIT. The full licence text and copyright line are in that repository's `LICENSE` file; it applies to these files. Refresh with `skills/pixel-art/bin/sync-pebbly-rules.cmd`.

## Hi3D source workflow

- **File:** `skills/concept-to-3d/bin/pa_wf01.json` (workflow 01, used by `build_graphs.py` to build the TRELLIS.2 and Hi3D API graphs)
- **Source:** https://github.com/pixelartistry/PixelArtistry-Hi3D (`workflows/`)
- **Licence:** MIT (installer and workflows), per that repository. The workflow only references model files by name; it contains no weights.

## Model names and graphs

The ComfyUI graphs in `skills/pixel-art/assets/` and `skills/blender-anim/assets/` name third-party model files. Naming a file grants no licence to it; each model's own licence applies when the setup downloads it.

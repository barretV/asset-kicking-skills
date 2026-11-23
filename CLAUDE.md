# CLAUDE.md

If the user asked you to set this repo up on their machine, follow [AGENTS.md](AGENTS.md) step by step. Never skip its confirmation steps: list every download (source, size, licence) and wait for the user's yes before installing or downloading anything.

If you are editing this repo itself:
- Skills live in `skills/<name>/SKILL.md` with their scripts beside them. Keep them project-neutral: no personal paths, names, game titles or API keys. Paths come from `$COMFYUI_DIR` or `~/.asset-kicking-skills/config.json`.
- Model files are listed in `setup/models.json`, never committed. Add size, licence and source for every new entry, and a row in LICENSES.md.
- Tier settings live in `setup/tiers.json`; keep TIERS.md in step with it. Mark anything not run on real hardware as untested.
- `setup/detect.py` must stay standard-library only and read-only.

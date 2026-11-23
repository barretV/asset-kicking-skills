# Game UI art with the forge loop

Menus and HUDs drawn in CSS or flat vector look generic. Painted parts with live text on top look made for the game. This page is the recipe behind `examples/ui/`: every frame, ribbon, medallion and icon came out of this loop, and every word on screen is real text.

## The rules
1. **Painted, not vector.** Thick dark ink with varied weight, a lit side and a shadow side, real material texture (wood grain, brushed metal, glossy liquid, cloth).
2. **One material language for the whole UI.** Pick two or three materials that belong to your game's world and use them on everything. The example uses chunky dark wood, gold trim with hex studs and rivets, and dripping translucent honey. Write yours down before the first job.
3. **No baked text, ever.** Paint blank plates, ribbons and frames; put live font text on top. Text stays sharp at any resolution, can be translated, and the art is reused across screens. Leave a flat face on every plate big enough for its longest label.
4. **Glow means something.** A soft halo marks what matters (selected, ready, new, rare), never everything at once. Add it in the engine (a tinted drop-shadow or bloom), not in the painting, so one asset serves every state.
5. **States are filters, not repaints.** Locked, disabled or "downed" versions are the same art through a greyscale/darken filter.
6. **Clean cutouts.** No halos, leftover background pockets or faded edges. Check on a magenta background; the forge sheets already use one.
7. **Reuse a small kit.** A card frame, a panel frame, a ribbon, a medallion, a seal and a button cover most screens. Forge these first and build screens from them before forging anything new.

## The job
art-forge-loop in illustration mode. The settings that produced the example kit:

| Setting | Value | Why |
|---|---|---|
| `mode` | `illustration` | painted, not pixel |
| `lora` | 0 | pixel LoRA off |
| `size` | 1024 | detail for edges and drips |
| `out_px` | 512 | export about 2x display size |
| `first_denoise` | 0.75 | keeps the init's silhouette, repaints everything else |
| `max_rounds` | 4 | |
| `bar` | 9.5 | |

**Start from a rough init, never from nothing.** Draw the piece's silhouette and colour blocks in code (an SVG of rectangles, hexes and blobs rasterised to PNG is enough): the frame's proportions, where the gems sit, the empty centre. txt2img invents a new layout every seed; img2img from a mock keeps the layout you need for the screen.

**Style prompt** (adapt the materials to your game):

> chunky stylised game UI ornament painting, thick dark varied ink outlines, painted dark wood planks and brushed gold trim with hex studs, glossy translucent honey dripping from the top edge, warm amber rim light, empty flat dark centre panel, no text, no letters, centred, flat lavender background

Name the empty areas ("empty flat dark centre panel", "blank ribbon face") and say "no text, no letters": the model loves to write gibberish on plates.

## Grade like a UI artist
On top of art-forge-loop's usual bar:
- The flat face is really flat and big enough for its text (no ornament or highlight in the text area).
- Same light direction, ink weight and materials as the rest of the kit; put the new piece next to an approved one on the sheet.
- Symmetric where it should be (frames, buttons). Mirror the better half in an image editor if the model drifts.
- Edges survive downscaling to display size: thin details under 2 px at display size disappear.

## Export and wire in
1. Trim, resize to about 2x display size, quantise to 256 colours. Icons should land around 15-25 KB, frames under 50 KB.
2. Frames that must stretch: nine-slice them (CSS `border-image`, or your engine's nine-slice sprite) with the corners and gems outside the stretch zone.
3. Live text on the plates; pick one display font for headings and one readable font for body text.
4. Glow and states through engine filters (see rules 4 and 5).

## Check the layout (mechanically, then by eye)
Write a small script for each screen (Playwright for web games, an editor script for engines) that reads element boxes and fails on:
- clipped or overflowing text, or text past a plate's flat face;
- content outside its frame, overlaps, anything drawn over text;
- text closer than about 6 px to a tile edge;
- uneven rows or baselines, mixed heading sizes in one row;
- dead empty bands over about 36 px.

Iterate until it reports zero issues, then look at full-size screenshots yourself. A script finds overlaps; only eyes find "this looks cheap".

## GPU cost on 6 GB
About a minute per 1024 image, two seeds per round, two or three rounds per piece: roughly 4-6 minutes a piece, so a kit of six parts is under an hour. Icons in bulk run well unattended under `/ralph-loop`.

-- Prints the frame count so the CLI can size a sprite sheet grid.
-- Called as: aseprite -b <sprite> --script frame_count.lua
local s = app.activeSprite
if s == nil then
  print("FRAMES=0")
  return
end
print("FRAMES=" .. #s.frames)

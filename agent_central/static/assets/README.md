# Assets

Pixel art assets used by Agent Central. See `/ASSETS_LICENSES.md` at the project root for license details.

## Inventory

- `tilesets/2dpig-pixel-office/` — side-view office structure, 5 characters, base furniture (CC0)
- `furniture/` — empty. A.3 skipped after no free side-view pack met style criteria; leaning into 2dPig's existing furniture as a constraint. See ASSETS_LICENSES.md "Save for Later" section.
- `characters/` — empty. Covered by 2dPig's 5 character sprites; future variety via Aseprite recoloring.
- `animations/` — empty. Character animations not used. Environment animations (monitor screens, status overlays, glows, particles) will be implemented in code during Step F polish.
- `ui/` — empty. Deferred to Step F polish.

## Conventions

- Visual direction: **side-view (cross-section / dollhouse-cutaway)**. Locked for Phase 1. Top-down deferred to a future "zoom out" phase.
- Tile size: 16×16 baseline (sprites in 2dPig's pack vary; treated as the visual reference).
- Style: clean modern pixel art with warm + saturated palette to harmonize with the amber UI.
- Every installed pack lives under its own subfolder named after the pack.

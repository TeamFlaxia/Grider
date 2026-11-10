<!-- SPDX-License-Identifier: Apache-2.0 -->

# Rendering dataflow mapping

Grider renders as a stencil dataflow: triangles/flow tests become tile-local
cellular updates, while per-pixel shading uses F32 dot products and
convolutions use neighbor halos.

## Stages

- **Setup.** `TRANSPOSE` and `ROW_BROADCAST`/`COL_BROADCAST` put tile setup
  (half-extents, barycentric denominators, perspective planes) into a
  per-row scalar that shaders reuse.
- **Rasterize.** Per-tile barycentric tests iterate pixels with `NEIGHBOR`
  halos for shared edges across tiles. Edge functions are `MUL`/`ADD` in
  F32; depth tests use `MIN`/`MAX` and `SEL`.
- **Shade.** Lambert/Blinn/PBR lighting is `DOT_ROW` plus normalizations
  (`grider.render.lambert`). Texture fetches stream via `GATHER` on
  cell-local SRAM and DMA ping-pong; output shading writes through `STORE`.
- **Filter/Post.** `grider.render.box_blur` and `sobel_edge` lower to
  `NEIGHBOR` shifts (8 directions) + F32 `ADD`/`MUL`. `resize_bilinear`
  stages filter taps so each cell samples neighbors only.
- **Blend/Composite.** Alpha blending is `SUB` (1-a), two `MUL`, and one
  `ADD` in F32 (`grider.examples.render_blend`, `grider.render.alpha_blend`).
  Perspective divide maps to F32 `DIV` emulation by iterated reciprocal
  multiplication (integer DIV covers index math).

## Host oracles

`grider.render` provides `box_blur`, `sobel_edge`, `bilinear_sample`,
`resize_bilinear`, `alpha_blend`, `barycentric`, `lambert`, and
`perspective_divide`. Tile examples `render_blur.py` and `render_blend.py`
execute the same output on the emulator. The `LATENCY` table in
`grider.dataflow` sizes raster->shade->blend pipelines.

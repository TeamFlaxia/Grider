<!-- SPDX-License-Identifier: Apache-2.0 -->

# AI dataflow mapping

Grider is a cellular dataflow device for AI: tiles translate streaming
producers into SIMD consumers without a shared instruction fetch stream.
The tile decodes once and broadcasts; the program provides lane masks that
select participating cells.

## Primitive strategies

- **GEMM / MAC chains.** `grider.lowering.lower_gemm16` keeps a BF16
  input in F32 accumulation via `MAC`. A dataflow tiling broadcasts A along
  rows and B along columns (`MOVI` + `MAC`). `TRANSPOSE` provides the
  B-transpose for attention K layouts and `DOT_ROW` collapses one query/key
  pair per row in a single instruction.
- **Attention.** QK scores are `DOT_ROW` per query row against replicated K
  (`grider.lowering.lower_qk_scores_row16`); scaling, softmax max/sum, and
  causal masks then map to `MUL` + `REDUCE_MAX` + `REDUCE_SUM` + `SEL`.
  `SCAN_SUM` implements prefix sums for histograms and categorical sampling.
- **Norms.** RMSNorm and LayerNorm use row `REDUCE_SUM` for mean and
  mean-square, `ROW_BROADCAST` to send the row scalar back to every lane,
  and F32 elementwise `MUL`/`SUB` for affine scaling. `rms_norm` in
  `grider.kernels` is the host oracle for iterators that expand reciprocal
  square roots into `ADD`/`MUL` Newton steps.
- **Activations and Gating.** GELU/SiLU/SwiGLU and RoPE are staged as
  `MAC`/`MUL` polynomials and `SEL` masks; RoPE pairs adjacent features
  with `NEIGHBOR` shifts and cosine/sine scalars via `ROW_BROADCAST`.
- **Gather/Scatter.** Embeddings, paged KV, and MoE routing use `GATHER` /
  `SCATTER` on cell-local SRAM plus `SCAN_SUM`/`REDUCE` histograms. Cross-
  tile halos remain `NEIGHBOR` based.
- **Fusion.** Fuse normalization, scaling, and activation in one tile pass
  to minimize register traffic. Producer/consumer tiles in the mesh form a
  dataflow graph (`grider.dataflow.estimate_pipeline`); double-buffered
  SRAM ping-pong hides DMA behind compute.

## Cycle estimates

`grider.dataflow.LATENCY` lists tile latencies: 2 (NOP/MOVI), 3
(single-read tile moves/reductions), 4 (two reads / GATHER), 5 (MAC/SEL).
`grider.benchmark` reports 256-lane BF16/F32 MAC and DOT rates at an assumed
clock. The RTL still issues one instruction at a time; per-tile issue
queues and elastic MAC stages are datapath primitives for future overlap.

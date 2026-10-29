# Burst DMA and banked SRAM

`PingPongTileMemory` models two SRAM banks, one streaming DMA write beat per
cycle, and a compute port that reads the active bank. The default DMA target is
the inactive bank, allowing a compute cycle and a DMA transfer to overlap.
Explicitly selecting the active bank models a same-bank conflict; compute has
priority and the transfer stalls for that cycle.

The counters report total, DMA, compute, and overlap cycles, conflict stalls,
words, and bytes. `words_per_cycle` is measured over active DMA cycles, so
same-bank stalls lower the reported rate. `swap_buffers` is allowed after a
burst completes and switches which bank compute reads.

`rtl/grider_banked_dma.sv` provides a streaming ready/valid burst port and a
synchronous compute port over two banks. The caller chooses the DMA bank and
uses `swap_bank` after a transfer and compute phase are complete. This module
is not yet wired into `grider_tile`; the current tile SRAM remains the existing
per-cell single-port memory.

# Changelog

## 0.3.0

- Add `leman2000_batch` and a reusable warm worker pool for efficient
  multi-file analysis.
- Add input-aligned batch results and structured per-file failures, including
  `continue_on_error` support.
- Add configurable batch progress reporting and duration-aware worker sizing.
- Bound long-audio MATLAB worker memory through streamed, disk-spooled
  auditory-nerve processing.
- Expand MATLAB/Octave parity, snapshot, worker-recovery, and package tests.

## 0.2.0

- Add the compiled MATLAB worker backend and make it the default runtime.
- Publish reproducible, digest-pinned model images.

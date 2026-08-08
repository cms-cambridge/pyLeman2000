# Streaming prototypes

Experimental helpers for memory-bounded Leman (2000) analysis.

## Status

| Stage | Helper | Parity |
| --- | --- | --- |
| Leaky integration / contextuality #3 | `leman_leaky_integration_chunk.m`, `leman_contextuality_comparison_stream.m` | exact |
| Periodicity pitch | `leman_periodicity_pitch_chunk.m`, `leman_periodicity_pitch_stream.m` | ≤ 1e-12 |
| ANI spool + block-read | `leman_calc_ani_spool.m`, `leman_read_ani_chunk.m`, `leman_downsample_ani_chunk.m`, `leman_ani_from_spool_chunk.m` | ≤ ~3e-14 |
| ANI → PP from spool | `leman_periodicity_pitch_from_spool.m` | ≤ ~3e-14 |

Default MATLAB `leman_2000_compute` (`detail <= 1`) uses the spool path.
`detail > 1` / `keep_*` still use the classic full-matrix path. Octave
`docker/octave/leman_2000.m` uses the same spool helpers.

## Run parity on musix

```bash
python scripts/streaming/run_parity.py contextuality \
  --host pmch2@musix.mus.cam.ac.uk
python scripts/streaming/run_parity.py periodicity \
  --host pmch2@musix.mus.cam.ac.uk
python scripts/streaming/run_parity.py pipeline \
  --host pmch2@musix.mus.cam.ac.uk
python scripts/streaming/run_parity.py ani \
  --host pmch2@musix.mus.cam.ac.uk
```

Or:

```bash
PYLEMAN2000_MATLAB_HOST=pmch2@musix.mus.cam.ac.uk \
  pytest -m matlab tests/test_streaming_parity.py
```

## Memory vs audio length

Systematic batch vs spool peak-PSS sweep (5–120 s) is saved under
[`artifacts/benchmark/path_memory_compare.md`](../../artifacts/benchmark/path_memory_compare.md)
(raw JSON alongside). Headline: batch ~**5.4 MB/s** PSS growth vs spool
~**0.8 MB/s**.

```bash
python scripts/streaming/run_path_memory_compare.py \
  --host pmch2@musix.mus.cam.ac.uk \
  --durations 5 15 30 60 90 120 \
  --hihat src/pyleman2000/data/hihat.wav
```

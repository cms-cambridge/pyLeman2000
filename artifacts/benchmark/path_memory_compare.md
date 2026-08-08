# Batch vs spool path memory

Systematic comparison of peak process memory for the classic Leman pipeline
versus the disk-spooled ANI path (mex → block-read `.ani` → streamed
downsample → chunked periodicity pitch → streamed contextuality).

Collected: `2026-08-08T16:53:04.668820+00:00`

## Setup

| Item | Value |
| --- | --- |
| Host | `pmch2@musix.mus.cam.ac.uk` |
| MATLAB | R2026a source mode + pinned IPEM |
| Audio | tiled hi-hat WAVs (`artifacts/benchmark/profile_*s_tiled_hihat.wav`) |
| Durations | 5, 15, 30, 60, 90, 120 s |
| ChunkLen | 1024 (downsampled ANI columns per PP chunk) |
| Metric | PSS from `/proc/self/smaps_rollup` at stage boundaries |
| Isolation | one fresh MATLAB process per `(duration, mode)` |

**Batch mode:** `IPEMCalcANI` → `IPEMPeriodicityPitch` → `IPEMContextualityIndex`.

**Spool mode:** `leman_calc_ani_spool` → `leman_periodicity_pitch_from_spool` →
`leman_contextuality_comparison_stream`.

Raw per-stage samples: [`path_memory_compare.json`](path_memory_compare.json).

Reproduce:

```bash
python scripts/streaming/run_path_memory_compare.py \
  --host pmch2@musix.mus.cam.ac.uk \
  --durations 5 15 30 60 90 120 \
  --hihat src/pyleman2000/data/hihat.wav
```

## Headline

| | Batch | Spool |
| --- | ---: | ---: |
| Peak PSS slope vs duration | **5.43 MB/s** | **0.79 MB/s** |
| Linear fit R² (peak PSS) | 0.997 | 0.75 |
| Peak PSS at ~120 s | 1368 MB | 806 MB |
| Saved at ~120 s | — | **562 MB** |

Batch growth is almost perfectly linear in audio length. Spool growth is ~7×
shallower; remaining climb is mostly accumulated PP plus MATLAB heap noise
(hence lower R² — e.g. 120 s peak slightly below 90 s).

## Peak PSS vs length

| Audio | Batch peak PSS | Spool peak PSS | Δ (spool − batch) | Batch Δ vs baseline | Spool Δ vs baseline |
| --- | ---: | ---: | ---: | ---: | ---: |
| 4.8 s | 752 MB | 739 MB | −13 MB | 98 MB | 87 MB |
| 14.8 s | 782 MB | 748 MB | −34 MB | 142 MB | 93 MB |
| 30.0 s | 869 MB | 739 MB | −130 MB | 216 MB | 101 MB |
| 60.1 s | 1015 MB | 797 MB | −217 MB | 366 MB | 143 MB |
| 90.1 s | 1203 MB | 837 MB | −366 MB | 555 MB | 181 MB |
| 120.1 s | 1368 MB | 806 MB | −562 MB | 716 MB | 163 MB |

Baseline is `after_setup` PSS (~640–655 MB MATLAB + IPEM). Δ = peak − baseline
for that run.

## Stage PSS (selected)

| Audio | Batch after_calc_ani | Spool after_ani_spool | Batch after PP | Spool after PP |
| --- | ---: | ---: | ---: | ---: |
| 4.8 s | 733 MB | 702 MB | 750 MB | 737 MB |
| 14.8 s | 731 MB | 713 MB | 780 MB | 742 MB |
| 30.0 s | 816 MB | 709 MB | 867 MB | 733 MB |
| 60.1 s | 947 MB | 751 MB | 1015 MB | 795 MB |
| 90.1 s | 1110 MB | 777 MB | 1203 MB | 835 MB |
| 120.1 s | 1250 MB | 747 MB | 1368 MB | 804 MB |

The split appears at ANI: batch materialises the full downsampled matrix (and
pays for `textread` of the raw `.ani`); spool leaves `.ani` on disk and never
holds the full ANI or full FANI.

## Linear fits

PSS in MB, \(T\) in seconds. Ordinary least squares over the six durations.

| Quantity | Fit | R² | Slope |
| --- | --- | ---: | ---: |
| Batch peak PSS | `708 + 5.43·T` | 0.997 | 5.43 MB/s |
| Spool peak PSS | `736 + 0.79·T` | 0.75 | 0.79 MB/s |
| Batch Δ vs baseline | `60 + 5.42·T` | 0.998 | 5.42 MB/s |
| Spool Δ vs baseline | `84 + 0.82·T` | 0.87 | 0.82 MB/s |
| Batch after_calc_ani | `681 + 4.69·T` | 0.993 | 4.69 MB/s |
| Spool after_ani_spool | `704 + 0.54·T` | 0.68 | 0.54 MB/s |

## Extrapolation

Using mean baseline ~649 MB + Δ-PSS slopes (batch 5.42 MB/s, spool 0.82 MB/s):

| Audio | Batch peak (est.) | Spool peak (est.) |
| --- | ---: | ---: |
| 5 min | ~2.3 GB | ~1.0 GB |
| 10 min | ~4.0 GB | ~1.2 GB |
| 30 min | ~10.5 GB | ~2.2 GB |
| 60 min | ~20 GB | ~3.7 GB |

Spool estimates assume PP accumulation stays the main variable cost. They do
not include `detail>1` / `keep_*` JSON payloads (unsupported on the stream
path by design).

## Related artifacts

| File | What |
| --- | --- |
| [`path_memory_compare.json`](path_memory_compare.json) | Full stage samples for this sweep |
| [`mex_memory_profile.md`](mex_memory_profile.md) | Mex-only PSS stays flat while `.ani` grows on disk |
| [`stage_memory_profile.md`](stage_memory_profile.md) | Earlier stage profile (batch + in-memory stream PP) |
| [`ani_speed_profile.md`](ani_speed_profile.md) | Wall-clock batch vs spool (ANI / ANI+PP) |

## Caveats

- Stage-boundary PSS can miss short spikes inside `textread` on the batch path.
- MATLAB often retains freed heap; prefer peaks and Δ-vs-baseline over
  absolute post-`clear` values.
- Harness: `scripts/streaming/profile_path_memory.m` +
  `scripts/streaming/run_path_memory_compare.py`.

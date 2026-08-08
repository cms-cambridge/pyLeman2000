# Stage memory profile

Collected: `2026-08-08T16:15:33.120626+00:00`

- Host: `pmch2@musix.mus.cam.ac.uk`
- MATLAB source mode against pinned IPEM
- Params: local=0.1, global=1.0

## Peak by audio length

| Audio | Peak RSS | Peak PSS |
| --- | ---: | ---: |
| 4.8 s | 981 MB | 752 MB |
| 30.0 s | 1110 MB | 879 MB |
| 60.1 s | 1270 MB | 1039 MB |
| 120.1 s | 1569 MB | 1338 MB |

## Stages (PSS, MB)

| Stage | 5s | 30s | 60s | 120s |
| --- | ---: | ---: | ---: | ---: |
| after_setup | 653 | 653 | 652 | 652 |
| after_read_wav | 680 | 688 | 697 | 716 |
| after_calc_ani | 731 | 817 | 983 | 1249 |
| after_clear_wav | 731 | 807 | 963 | 1209 |
| after_stream_pp | 750 | 830 | 986 | 1235 |
| after_stream_contextuality | 751 | 832 | 988 | 1237 |
| after_clear_stream_outputs | 752 | 832 | 988 | 1237 |
| after_periodicity_pitch | 752 | 879 | 1039 | 1338 |
| after_clear_ani | 752 | 879 | 988 | 1237 |
| after_contextuality | 752 | 879 | 989 | 1238 |
| after_clear_ppfani | 752 | 841 | 938 | 1137 |
| after_clear_all | 752 | 841 | 938 | 1137 |

## Notes

- RSS/PSS are sampled from `/proc/self` inside the MATLAB process.
- `after_calc_ani` is the first point where the full ANI matrix exists.
- `after_stream_*` runs streamed PP/contextuality while ANI is still held.
- `after_periodicity_pitch` is the classic full-matrix PP path.
- MATLAB does not always return freed arrays to the OS; deltas from
  `after_setup` are more informative than absolute clears.

## Interpretation

Fixed baseline is ~650 MB PSS (MATLAB + IPEM). Above that, growth is
nearly linear in audio length:

| Quantity | Fit on 30–120 s |
| --- | --- |
| PSS after `IPEMCalcANI` − baseline | ~4.8 MB/s |
| Peak with streamed PP/contextuality − baseline | ~4.5 MB/s |
| Peak with classic PP (includes full FANI) − baseline | ~5.1 MB/s |

The final downsampled ANI matrix itself is only ~0.84 MB/s
(`40 × 2756 Hz × 8 bytes`). Observed `after_calc_ani` growth is ~5× larger,
so most of the ANI-stage footprint is temporary / undownsampled / mex
overhead, not the final matrix alone.

Streaming PP+contextuality while holding ANI adds little (~20–30 MB) and
avoids the classic path's extra full-size FANI (`PPFANI`), which is another
~0.8 MB/s. That is real, but secondary: **ANI production dominates**.

Extrapolating the stream-while-holding-ANI peak
(`~650 + 4.5 × T_sec` MB):

| Audio | Approx peak PSS |
| --- | ---: |
| 10 min | ~3.4 GB |
| 30 min | ~8.8 GB |
| 60 min | ~17 GB |

So Option A (keep mex, stream after ANI) helps and removes FANI duplication,
but does not make hour-scale analysis comfortable. True long-audio support
still needs streaming or disk-spooled ANI production (Option B / middle-path
step 2), not just streamed PP.

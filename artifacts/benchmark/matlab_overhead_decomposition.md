# MATLAB startup vs compute (5s)

Collected: `2026-08-06T08:06:29.286449+00:00`

Image: `ghcr.io/pmcharrison/leman_2000:latest`  
Params: local=`0.1,0.5`, global=`1.0,2.0`, detail=`5`  
Repeats: 3 (after 1 warmup), interleaved short/5s oneshots.

## Raw means

| Condition | short (0.37s) | 5s | delta |
| --- | ---: | ---: | ---: |
| Empty container cycle (`docker run --entrypoint /bin/true`) | 11.328s | — | — |
| Full oneshot (`docker run`, as leman2000R) | 21.348s | 24.442s | 3.094s |
| Warm container + `docker exec` | 7.073s | 10.200s | 3.127s |

## Linear decomposition `T ≈ overhead + k · duration`

### Oneshot (includes container create/teardown + MCR + model)

- k ≈ **0.668 s per audio-second**
- fixed overhead ≈ **21.101 s**
- estimated compute for 5s ≈ **3.341 s**
- overhead share of 5s oneshot ≈ **86.3%**

### Warm exec (excludes container create/teardown; still pays MCR each exec)

- k ≈ **0.675 s per audio-second**
- fixed overhead (mostly MCR startup) ≈ **6.823 s**
- estimated compute for 5s ≈ **3.377 s**
- overhead share of 5s warm exec ≈ **66.9%**

## Verdict

If overhead share of the 5s oneshot is ≳50%, the earlier claim holds: even a 5s
MATLAB analysis is still dominated by startup/fixed cost, not audio-length
compute.

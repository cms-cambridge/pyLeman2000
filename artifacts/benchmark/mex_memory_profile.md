# Mex-only memory profile

Collected: `2026-08-08T16:20:36.120655+00:00`

- Host: `pmch2@musix.mus.cam.ac.uk`
- Measures `IPEMProcessAuditoryModelSafe` without loading `.ani`
- External `/proc` poll every 50 ms during the mex call

| Audio | Before mex PSS | After mex PSS | Polled peak PSS | ANI file |
| --- | ---: | ---: | ---: | ---: |
| 30.0 s | 703 MB | 703 MB | 703 MB | 165 MB |
| 120.1 s | 714 MB | 714 MB | 715 MB | 658 MB |

## Notes

- If polled peak ≈ before/after mex, the mex itself is not the RAM hog.
- Large `.ani` on disk with flat PSS supports disk-spooling.

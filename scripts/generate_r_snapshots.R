library(leman2000R)

wav <- "/workspace/src/pyleman2000/data/hihat.wav"
out_dir <- "/workspace/tests/snapshots"

res <- leman2000(
  input_file = wav,
  local_decay_sec = c(0.1, 0.2),
  global_decay_sec = c(1, 2),
  windows = list(
    c(0.0, 0.1),
    c(0.1, 0.2),
    c(0.2, 0.3)
  )
)

meta <- data.frame(
  audio_length_sec = res$audio_length_sec,
  num_channels = res$num_channels,
  sample_rate = res$sample_rate
)
write.csv(meta, file.path(out_dir, "r_hihat_meta.csv"), row.names = FALSE)

write.csv(
  res$local_global_comparison,
  file.path(out_dir, "r_hihat_local_global_comparison.csv"),
  row.names = FALSE
)
write.csv(
  res$windowed_local_global_comparison,
  file.path(out_dir, "r_hihat_windowed_local_global_comparison.csv"),
  row.names = FALSE
)

cat("Wrote snapshots\n")
print(meta)
print(utils::head(res$local_global_comparison))
print(res$windowed_local_global_comparison)

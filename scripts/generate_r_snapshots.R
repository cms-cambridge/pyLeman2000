if (!requireNamespace("remotes", quietly = TRUE)) {
  stop("Install remotes before regenerating snapshots: install.packages(\"remotes\")")
}

leman2000r_ref <- "pmcharrison/leman2000R@6067bfdfad2a5ce4910790cf6f7f2e64a7d7837b"
leman2000r_sha <- "6067bfdfad2a5ce4910790cf6f7f2e64a7d7837b"
docker_image <- paste0(
  "ghcr.io/pmcharrison/leman_2000@",
  "sha256:08d5ce84b9844954473832af65188f8f56fdfc8bcc3c64e0307e532a062e2442"
)
latest_tag <- "ghcr.io/pmcharrison/leman_2000:latest"

args <- commandArgs(trailingOnly = FALSE)
file_arg <- grep("^--file=", args, value = TRUE)
if (length(file_arg) != 1) {
  stop("Run this script with Rscript")
}
script_path <- normalizePath(sub("^--file=", "", file_arg))
repo_root <- normalizePath(file.path(dirname(script_path), ".."))
wav <- file.path(repo_root, "src", "pyleman2000", "data", "hihat.wav")
out_dir <- file.path(repo_root, "tests", "snapshots")

if (!file.exists(wav)) {
  stop("Example WAV does not exist: ", wav)
}
dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)

message("Installing pinned leman2000R revision ", leman2000r_sha)
remotes::install_github(leman2000r_ref, upgrade = "never", quiet = TRUE)
suppressPackageStartupMessages(library(leman2000R))

installed_sha <- utils::packageDescription("leman2000R")$RemoteSha
if (is.null(installed_sha) || !identical(installed_sha, leman2000r_sha)) {
  stop(
    "Installed leman2000R revision is ",
    if (is.null(installed_sha)) "unknown" else installed_sha,
    "; expected ",
    leman2000r_sha
  )
}

if (system2("docker", c("pull", docker_image)) != 0) {
  stop("Could not pull pinned Docker image")
}

previous_latest_id <- system2(
  "docker",
  c("image", "inspect", "--format", "{{.Id}}", latest_tag),
  stdout = TRUE,
  stderr = FALSE
)
had_previous_latest <- is.null(attr(previous_latest_id, "status")) ||
  attr(previous_latest_id, "status") == 0
if (had_previous_latest) {
  previous_latest_id <- previous_latest_id[[1]]
} else {
  previous_latest_id <- NULL
}

restore_latest_tag <- function() {
  if (!is.null(previous_latest_id)) {
    system2("docker", c("tag", previous_latest_id, latest_tag))
  } else {
    system2("docker", c("rmi", latest_tag), stdout = FALSE, stderr = FALSE)
  }
}
on.exit(restore_latest_tag(), add = TRUE)

if (system2("docker", c("tag", docker_image, latest_tag)) != 0) {
  stop("Could not tag pinned Docker image for leman2000R")
}

write_csv_atomic <- function(value, filename) {
  destination <- file.path(out_dir, filename)
  temporary <- tempfile(pattern = paste0(filename, "-"), tmpdir = out_dir)
  write.csv(value, temporary, row.names = FALSE)
  on.exit({
    if (!is.null(temporary) && file.exists(temporary)) {
      unlink(temporary)
    }
  }, add = TRUE)

  if (file.rename(temporary, destination)) {
    temporary <- NULL
    return(invisible(destination))
  }

  backup <- NULL
  if (file.exists(destination)) {
    backup <- paste0(destination, ".bak")
    if (!file.rename(destination, backup)) {
      stop("Could not back up existing snapshot: ", destination)
    }
  }
  if (!file.rename(temporary, destination)) {
    if (!is.null(backup) && file.exists(backup)) {
      file.rename(backup, destination)
    }
    stop("Could not replace snapshot: ", destination)
  }
  temporary <- NULL
  if (!is.null(backup)) {
    unlink(backup)
  }
  invisible(destination)
}

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
stopifnot(
  identical(
    names(res$local_global_comparison),
    c(
      "local_decay_sec",
      "global_decay_sec",
      "time_sec",
      "running_correlation"
    )
  ),
  identical(
    names(res$windowed_local_global_comparison),
    c(
      "local_decay_sec",
      "global_decay_sec",
      "window_id",
      "window_start",
      "window_end",
      "local_global_correlation"
    )
  ),
  nrow(res$local_global_comparison) == 104,
  nrow(res$windowed_local_global_comparison) == 12
)

write_csv_atomic(meta, "r_hihat_meta.csv")
write_csv_atomic(
  res$local_global_comparison,
  "r_hihat_local_global_comparison.csv"
)
write_csv_atomic(
  res$windowed_local_global_comparison,
  "r_hihat_windowed_local_global_comparison.csv"
)
writeLines(
  c(
    paste("Generated:", format(Sys.time(), tz = "UTC", usetz = TRUE)),
    paste("leman2000R:", as.character(packageVersion("leman2000R"))),
    paste("Source revision:", installed_sha),
    paste("Docker image:", docker_image),
    paste(
      "Windowing note: R uses half-open [start, end); Python pyLeman2000 uses",
      "closed [start, end]. These hi-hat snapshots have no samples exactly on",
      "window boundaries 0.1/0.2/0.3, so values still match."
    ),
    "",
    capture.output(sessionInfo())
  ),
  file.path(out_dir, "r_hihat_provenance.txt")
)

cat("Wrote snapshots\n")
print(meta)
print(utils::head(res$local_global_comparison))
print(res$windowed_local_global_comparison)

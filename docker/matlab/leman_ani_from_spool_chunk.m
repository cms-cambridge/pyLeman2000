function [aniChunk, state] = leman_ani_from_spool_chunk(meta, nDsCols, state)
% Block-read a spooled .ani file, trim padding, and stream-downsample.
%
% Never loads the full raw ANI into memory. Uses a trailing-line buffer so
% the final meta.trim_cols lines (auditory-model pad) are discarded without
% a separate line-count pass.
%
% Parameters
% ----------
% meta :
%     Struct from leman_calc_ani_spool.
% nDsCols :
%     Target number of downsampled columns to return (may be fewer at EOF).
% state :
%     Opaque state from a previous call, or [] at the start.
%
% Returns
% -------
% aniChunk :
%     [nChannels x n] at meta.final_sample_freq (n <= nDsCols).
% state :
%     Updated state (.eof true when finished).

  if nargin < 3
    state = [];
  end
  if nDsCols < 1
    error('leman_ani_from_spool_chunk: nDsCols must be >= 1');
  end

  if isempty(state)
    state = init_state(meta);
  end
  if state.eof
    aniChunk = zeros(meta.n_channels, 0);
    return
  end

  parts = {};
  n_have = 0;
  raw_batch = max(meta.downsample_factor * nDsCols, meta.downsample_factor);

  while n_have < nDsCols && ~state.eof
    if size(state.ds_buf, 2) > 0
      take = min(size(state.ds_buf, 2), nDsCols - n_have);
      parts{end + 1} = state.ds_buf(:, 1:take); %#ok<AGROW>
      state.ds_buf = state.ds_buf(:, take + 1:end);
      n_have = n_have + take;
      continue
    end

    if state.ds_state.finalised
      state.eof = true;
      break
    end

    [raw, state] = read_next_raw(meta, state, raw_batch);
    if isempty(raw)
      if state.raw_eof
        [ds, state.ds_state] = leman_downsample_ani_chunk( ...
          zeros(meta.n_channels, 0), meta.downsample_factor, state.ds_state);
      else
        break
      end
    else
      [ds, state.ds_state] = leman_downsample_ani_chunk( ...
        raw, meta.downsample_factor, state.ds_state);
      if isempty(ds) && state.raw_eof && ~state.ds_state.finalised
        [ds, state.ds_state] = leman_downsample_ani_chunk( ...
          zeros(meta.n_channels, 0), meta.downsample_factor, state.ds_state);
      end
    end

    if isempty(ds)
      if state.ds_state.finalised
        state.eof = true;
      end
      break
    end

    take = min(size(ds, 2), nDsCols - n_have);
    parts{end + 1} = ds(:, 1:take); %#ok<AGROW>
    state.ds_buf = ds(:, take + 1:end);
    n_have = n_have + take;
    if state.ds_state.finalised && isempty(state.ds_buf)
      state.eof = true;
    end
  end

  if isempty(parts)
    aniChunk = zeros(meta.n_channels, 0);
  else
    aniChunk = [parts{:}];
  end
end

function state = init_state(meta)
  fid = fopen(meta.ani_path, 'r');
  if fid < 0
    error('leman_ani_from_spool_chunk: cannot open %s', meta.ani_path);
  end
  state = struct( ...
    'fid', fid, ...
    'read_state', struct('lines_read', 0, 'eof', false), ...
    'ds_state', leman_downsample_ani_init( ...
      meta.n_channels, meta.downsample_factor), ...
    'ds_buf', zeros(meta.n_channels, 0), ...
    'skip_head', meta.trim_cols, ...
    'tail', zeros(meta.n_channels, 0), ...
    'raw_eof', false, ...
    'eof', false);
end

function [raw, state] = read_next_raw(meta, state, n_wanted)
% Read raw lines, skip leading pad, hold trailing pad in state.tail.
  if state.raw_eof
    raw = zeros(meta.n_channels, 0);
    return
  end

  raw_parts = {};
  n_got = 0;
  while n_got < n_wanted && ~state.read_state.eof
    [chunk, state.read_state] = leman_read_ani_chunk( ...
      state.fid, max(n_wanted - n_got, 1) + meta.trim_cols, ...
      meta.n_channels, state.read_state);
    if isempty(chunk)
      break
    end

    if state.skip_head > 0
      take = min(state.skip_head, size(chunk, 2));
      chunk = chunk(:, take + 1:end);
      state.skip_head = state.skip_head - take;
      if isempty(chunk)
        continue
      end
    end

    combined = [state.tail, chunk];
    if size(combined, 2) > meta.trim_cols
      n_emit = size(combined, 2) - meta.trim_cols;
      emit_n = min(n_emit, n_wanted - n_got);
      raw_parts{end + 1} = combined(:, 1:emit_n); %#ok<AGROW>
      n_got = n_got + emit_n;
      state.tail = combined(:, emit_n + 1:end);
    else
      state.tail = combined;
    end
  end

  if state.read_state.eof
    % Release any non-pad samples still held for the trailing window, then
    % drop the final trim_cols pad lines.
    if size(state.tail, 2) > meta.trim_cols
      extra = state.tail(:, 1:end - meta.trim_cols);
      raw_parts{end + 1} = extra; %#ok<AGROW>
    end
    state.tail = zeros(meta.n_channels, 0);
    state.raw_eof = true;
    if state.fid >= 0
      fclose(state.fid);
      state.fid = -1;
    end
  end

  if isempty(raw_parts)
    raw = zeros(meta.n_channels, 0);
  else
    raw = [raw_parts{:}];
  end
end

function [dsChunk, state] = leman_downsample_ani_chunk(rawChunk, factor, state)
% Streaming equivalent of resample(rawChunk', 1, factor)'.
%
% Uses FIR coefficients from the local resample(), with an auto-discovered
% decimation phase / leading trim so chunked processing matches a single
% resample call on MATLAB and Octave.
%
% Parameters
% ----------
% rawChunk :
%     [nChannels x nTime] at the raw ANI rate (11025 Hz). Pass an empty
%     chunk after EOF to flush the FIR tail and finalise length. To create
%     state without data, call leman_downsample_ani_init first.
% factor :
%     Integer downsample factor (IPEM default 4).
% state :
%     Opaque state from a previous call, or [] at the start (requires a
%     non-empty rawChunk so channel count is known).
%
% Returns
% -------
% dsChunk :
%     Newly available [nChannels x nDs] samples at the downsampled rate.
% state :
%     Updated state for the next chunk.

  if nargin < 3
    state = [];
  end
  if factor < 1 || factor ~= floor(factor)
    error('leman_downsample_ani_chunk: factor must be a positive integer');
  end

  n_chan = size(rawChunk, 1);
  n_samp = size(rawChunk, 2);

  if isempty(state)
    if n_chan < 1
      error( ...
        ['leman_downsample_ani_chunk: cannot init state from empty ', ...
         'chunk; use leman_downsample_ani_init']);
    end
    state = leman_downsample_ani_init(n_chan, factor);
  elseif n_samp > 0 && state.n_channels ~= n_chan
    error( ...
      'leman_downsample_ani_chunk: expected %d channels, got %d', ...
      state.n_channels, n_chan);
  end

  if state.finalised
    dsChunk = zeros(state.n_channels, 0);
    return
  end

  if n_samp > 0
    [pending, state] = filter_decimate(rawChunk, state);
    state.n_in = state.n_in + n_samp;
    state.pending = [state.pending, pending];
  elseif ~state.flushed
    flush = zeros(state.n_channels, max(state.Lb - 1, 0));
    [pending, state] = filter_decimate(flush, state);
    state.pending = [state.pending, pending];
    state.flushed = true;
  end

  [dsChunk, state] = release_pending(state);
end

function [pending, state] = filter_decimate(rawChunk, state)
  n_chan = state.n_channels;
  zi = state.zi;
  phase = state.phase;
  pending = zeros(n_chan, 0);
  keep_idx = [];

  for ch = 1:n_chan
    [y, zi(:, ch)] = filter(state.b, 1, rawChunk(ch, :).', zi(:, ch));
    if ch == 1
      keep_idx = zeros(1, numel(y));
      k = 0;
      ph = phase;
      for i = 1:numel(y)
        if ph == 0
          k = k + 1;
          keep_idx(k) = i;
        end
        ph = mod(ph + 1, state.factor);
      end
      keep_idx = keep_idx(1:k);
      phase = ph;
      pending = zeros(n_chan, k);
    end
    if size(pending, 2) > 0
      pending(ch, :) = y(keep_idx).';
    end
  end

  state.zi = zi;
  state.phase = phase;
end

function [dsChunk, state] = release_pending(state)
  if state.skip_remaining > 0 && size(state.pending, 2) > 0
    take = min(state.skip_remaining, size(state.pending, 2));
    state.pending = state.pending(:, take + 1:end);
    state.skip_remaining = state.skip_remaining - take;
  end

  want = ceil(state.n_in / state.factor);
  avail = want - state.n_out;
  n_emit = min(size(state.pending, 2), max(avail, 0));
  dsChunk = state.pending(:, 1:n_emit);
  state.pending = state.pending(:, n_emit + 1:end);
  state.n_out = state.n_out + n_emit;

  if state.flushed
    state.pending = zeros(state.n_channels, 0);
    state.finalised = true;
  end
end

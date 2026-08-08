function [ppChunk, state] = leman_periodicity_pitch_chunk(aniChunk, sampleFreq, state, varargin)
% Emit periodicity-pitch frames for one ANI chunk, carrying filter state.
%
% Matches IPEMPeriodicityPitch when chunks are processed in order with the
% returned state. Does not materialise the full FANI matrix.
%
% Parameters
% ----------
% aniChunk :
%     Channels-by-samples auditory nerve image chunk (<= 40 channels).
% sampleFreq :
%     ANI sample rate in Hz.
% state :
%     Opaque state from a previous call, or [] / omitted at the start.
% varargin :
%     Name-value pairs: LowFrequency (default 80), FrameWidth (0.064),
%     FrameStepSize (0.010).
%
% Returns
% -------
% ppChunk :
%     Period-by-frames matrix of newly completed periodicity-pitch frames
%     (may be empty if the chunk did not finish any frame).
% state :
%     Updated state for the next chunk.

  if nargin < 3
    state = [];
  end

  p = inputParser;
  addParameter(p, 'LowFrequency', 80, @(x) isnumeric(x) && isscalar(x));
  addParameter(p, 'FrameWidth', 0.064, @(x) isnumeric(x) && isscalar(x));
  addParameter(p, 'FrameStepSize', 0.010, @(x) isnumeric(x) && isscalar(x));
  parse(p, varargin{:});
  opts = p.Results;

  n_chan = size(aniChunk, 1);
  n_samp = size(aniChunk, 2);
  if n_chan > 40
    error('leman_periodicity_pitch_chunk: Rows > 40');
  end

  if isempty(state)
    state = init_state(n_chan, sampleFreq, opts);
  else
    if state.n_chan ~= n_chan && n_samp > 0
      error( ...
        'leman_periodicity_pitch_chunk: expected %d channels, got %d', ...
        state.n_chan, n_chan);
    end
  end

  if n_samp == 0
    ppChunk = zeros(state.frame_width, 0);
    return
  end

  % Filter each channel as a column vector. Transposing a one-sample chunk
  % yields a row vector, which filter() would treat as a single channel.
  fani_chunk = zeros(n_chan, n_samp);
  zf = zeros(size(state.zi));
  for ch = 1:n_chan
    [y, zf(:, ch)] = filter( ...
      state.B, state.A, aniChunk(ch, :).', state.zi(:, ch));
    fani_chunk(ch, :) = y.';
  end
  state.zi = zf;

  state.ani_buf = [state.ani_buf, aniChunk];
  state.fani_raw = [state.fani_raw, fani_chunk];

  n_buf = size(state.ani_buf, 2);
  if n_buf <= state.the_delay
    ppChunk = zeros(state.frame_width, 0);
    return
  end

  fani_new = state.ani_buf(:, 1:n_buf - state.the_delay) ...
    - state.fani_raw(:, 1 + state.the_delay:n_buf);
  fani_new(fani_new < 0) = 0;

  state.ani_buf = state.ani_buf(:, n_buf - state.the_delay + 1:n_buf);
  state.fani_raw = state.fani_raw(:, n_buf - state.the_delay + 1:n_buf);

  state.fani_frame_buf = [state.fani_frame_buf, fani_new];
  [ppChunk, state] = emit_frames(state);
end

function state = init_state(n_chan, sampleFreq, opts)
  half_fs = sampleFreq / 2;
  frame_width = round(opts.FrameWidth * sampleFreq);
  frame_step = round(opts.FrameStepSize * sampleFreq);
  [B, A] = butter(2, opts.LowFrequency / half_fs);
  filt_order = max(numel(A), numel(B)) - 1;
  H = impz(B, A);
  [~, max_index] = max(H);
  the_delay = max_index - 1;

  state = struct();
  state.n_chan = n_chan;
  state.sample_freq = sampleFreq;
  state.B = B;
  state.A = A;
  state.zi = zeros(filt_order, n_chan);
  state.the_delay = the_delay;
  state.frame_width = frame_width;
  state.frame_width2 = frame_width * 2;
  state.frame_step = frame_step;
  state.out_sample_freq = sampleFreq / frame_step;
  state.out_periods = 0:1 / sampleFreq:(frame_width / sampleFreq - 1 / sampleFreq);
  state.ani_buf = zeros(n_chan, 0);
  state.fani_raw = zeros(n_chan, 0);
  state.fani_frame_buf = zeros(n_chan, 0);
  state.fani_origin = 1;
  state.next_frame_start = 1;
end

function [ppChunk, state] = emit_frames(state)
  n_fani = size(state.fani_frame_buf, 2);
  fani_end = state.fani_origin + n_fani - 1;
  frames = {};
  the_zeroes = zeros(1, state.frame_width);

  while state.next_frame_start + state.frame_width2 - 1 <= fani_end
    local_i = state.next_frame_start - state.fani_origin + 1;
    segment = state.fani_frame_buf( ...
      :, local_i:local_i + state.frame_width2 - 1);
    sum_auto = zeros(1, state.frame_width);
    for j = 1:state.n_chan
      auto_corr = xcorr( ...
        [the_zeroes, segment(j, 1:state.frame_width)], ...
        segment(j, :), ...
        state.frame_width);
      sum_auto = sum_auto + auto_corr(state.frame_width + 2:state.frame_width2 + 1);
    end
    frames{end + 1} = fliplr(sum_auto)'; %#ok<AGROW>
    state.next_frame_start = state.next_frame_start + state.frame_step;
  end

  if isempty(frames)
    ppChunk = zeros(state.frame_width, 0);
  else
    ppChunk = [frames{:}];
  end

  keep_from = state.next_frame_start;
  if keep_from > state.fani_origin
    drop = keep_from - state.fani_origin;
    if drop >= n_fani
      state.fani_frame_buf = zeros(state.n_chan, 0);
      state.fani_origin = keep_from;
    elseif drop > 0
      state.fani_frame_buf = state.fani_frame_buf(:, drop + 1:end);
      state.fani_origin = keep_from;
    end
  end
end

function [outSignal, state] = leman_leaky_integration_chunk( ...
    inSignal, sampleFreq, halfDecaySec, state, flushEnlargementSec)
% Integrate one chunk with the IPEM leaky-integrator recurrence.
%
% Matches IPEMLeakyIntegration for enlargement_sec == 0 when chunks are
% processed in order with carried state. Optional flushEnlargementSec
% appends trailing zeros and advances the integrator once, at the end of
% a stream (same role as inEnlargement in IPEMLeakyIntegration).
%
% Parameters
% ----------
% inSignal :
%     Channels-by-samples matrix for this chunk (may be empty when only
%     flushing enlargement).
% sampleFreq :
%     Sample rate in Hz.
% halfDecaySec :
%     Half-decay time in seconds.
% state :
%     Previous integrator state (channels-by-1), or [] / omitted at start.
% flushEnlargementSec :
%     Extra zero-padding duration in seconds applied after inSignal.
%     Empty or omitted means 0.
%
% Returns
% -------
% outSignal :
%     Integrated output for inSignal plus any flush padding.
% state :
%     Final integrator state (channels-by-1), or [] when there was no
%     output.

  if nargin < 4
    state = [];
  end
  if nargin < 5 || isempty(flushEnlargementSec)
    flushEnlargementSec = 0;
  end

  if halfDecaySec ~= 0
    integrator = 2^(-1 / (sampleFreq * halfDecaySec));
  else
    integrator = 0;
  end

  n_in = size(inSignal, 2);
  n_pad = round(sampleFreq * flushEnlargementSec);
  n_out = n_in + n_pad;
  n_chan = size(inSignal, 1);
  if n_chan == 0 && ~isempty(state)
    n_chan = size(state, 1);
  end

  if n_out == 0
    outSignal = zeros(n_chan, 0);
    return
  end

  if n_pad > 0
    if n_in == 0
      matrix = zeros(n_chan, n_pad);
    else
      matrix = [inSignal, zeros(n_chan, n_pad)];
    end
  else
    matrix = inSignal;
  end

  outSignal = zeros(size(matrix));
  if isempty(state)
    outSignal(:, 1) = matrix(:, 1);
    start_idx = 2;
  else
    if size(state, 1) ~= size(matrix, 1)
      error( ...
        'leman_leaky_integration_chunk: state has %d channels, signal has %d', ...
        size(state, 1), size(matrix, 1));
    end
    outSignal(:, 1) = state * integrator + matrix(:, 1);
    start_idx = 2;
  end

  for j = start_idx:size(matrix, 2)
    outSignal(:, j) = outSignal(:, j - 1) * integrator + matrix(:, j);
  end

  state = outSignal(:, end);
end

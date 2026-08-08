function running_corr = leman_contextuality_comparison_stream( ...
    periodicityPitch, sampleFreq, localDecaySec, globalDecaySec, chunkLen)
% Stream the Leman local/global comparison (IPEM contextuality #3).
%
% Processes periodicityPitch in successive column chunks while carrying
% leaky-integrator state. With enlargement 0 this matches the fifth output
% of IPEMContextualityIndex(..., [], local, global, 0, 0) used by
% pyLeman2000.
%
% Parameters
% ----------
% periodicityPitch :
%     Period-by-time matrix (IPEMPeriodicityPitch outSignal).
% sampleFreq :
%     Sample rate of periodicityPitch in Hz.
% localDecaySec :
%     Local half-decay time in seconds.
% globalDecaySec :
%     Global half-decay time in seconds.
% chunkLen :
%     Columns per chunk. Empty/omitted uses the full signal (one chunk).
%
% Returns
% -------
% running_corr :
%     1-by-T row vector of local/global correlations.

  if nargin < 5 || isempty(chunkLen)
    chunkLen = size(periodicityPitch, 2);
  end
  if chunkLen < 1
    error('leman_contextuality_comparison_stream: chunkLen must be >= 1');
  end

  n_time = size(periodicityPitch, 2);
  running_corr = zeros(1, n_time);
  local_state = [];
  global_state = [];
  out_idx = 0;

  ws = warning('query');
  warning('off');
  cleanup = onCleanup(@() warning(ws)); %#ok<NASGU>

  for start_col = 1:chunkLen:n_time
    stop_col = min(n_time, start_col + chunkLen - 1);
    chunk = periodicityPitch(:, start_col:stop_col);

    [local_img, local_state] = leman_leaky_integration_chunk( ...
      chunk, sampleFreq, localDecaySec, local_state, 0);
    [global_img, global_state] = leman_leaky_integration_chunk( ...
      chunk, sampleFreq, globalDecaySec, global_state, 0);

    for j = 1:size(chunk, 2)
      value = corrcoef(global_img(:, j), local_img(:, j));
      out_idx = out_idx + 1;
      running_corr(out_idx) = value(1, 2);
    end
  end
end

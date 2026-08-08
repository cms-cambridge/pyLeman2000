function [pp, state] = leman_periodicity_pitch_stream( ...
    ani, sampleFreq, chunkLen, varargin)
% Stream IPEMPeriodicityPitch over ANI column chunks.
%
% Parameters match leman_periodicity_pitch_chunk, plus chunkLen (columns
% per chunk; empty uses the full signal).

  if nargin < 3 || isempty(chunkLen)
    chunkLen = size(ani, 2);
  end
  if chunkLen < 1
    error('leman_periodicity_pitch_stream: chunkLen must be >= 1');
  end

  state = [];
  parts = {};
  n_time = size(ani, 2);
  for start_col = 1:chunkLen:max(n_time, 1)
    if n_time == 0
      break
    end
    stop_col = min(n_time, start_col + chunkLen - 1);
    [pp_chunk, state] = leman_periodicity_pitch_chunk( ...
      ani(:, start_col:stop_col), sampleFreq, state, varargin{:});
    if ~isempty(pp_chunk)
      parts{end + 1} = pp_chunk; %#ok<AGROW>
    end
  end

  if isempty(parts)
    if isempty(state)
      % Initialise metadata even for empty input.
      [~, state] = leman_periodicity_pitch_chunk( ...
        zeros(size(ani, 1), 0), sampleFreq, [], varargin{:});
    end
    pp = zeros(state.frame_width, 0);
  else
    pp = [parts{:}];
  end
end

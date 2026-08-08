function [pp, state] = leman_periodicity_pitch_from_spool( ...
    meta, dsChunkLen, varargin)
% Stream periodicity pitch from a spooled .ani without a full ANI matrix.
%
% Parameters
% ----------
% meta :
%     Struct from leman_calc_ani_spool.
% dsChunkLen :
%     Downsampled ANI columns per chunk fed to periodicity pitch.
% varargin :
%     Forwarded to leman_periodicity_pitch_chunk (LowFrequency, etc.).

  if nargin < 2 || isempty(dsChunkLen)
    dsChunkLen = 256;
  end
  if dsChunkLen < 1
    error('leman_periodicity_pitch_from_spool: dsChunkLen must be >= 1');
  end

  ani_state = [];
  pp_state = [];
  parts = {};
  while true
    [ani_chunk, ani_state] = leman_ani_from_spool_chunk( ...
      meta, dsChunkLen, ani_state);
    if isempty(ani_chunk)
      break
    end
    [pp_chunk, pp_state] = leman_periodicity_pitch_chunk( ...
      ani_chunk, meta.final_sample_freq, pp_state, varargin{:});
    if ~isempty(pp_chunk)
      parts{end + 1} = pp_chunk; %#ok<AGROW>
    end
    if ani_state.eof
      break
    end
  end

  if isempty(parts)
    if isempty(pp_state)
      [~, pp_state] = leman_periodicity_pitch_chunk( ...
        zeros(meta.n_channels, 0), meta.final_sample_freq, [], varargin{:});
    end
    pp = zeros(pp_state.frame_width, 0);
  else
    pp = [parts{:}];
  end
  state = pp_state;
end

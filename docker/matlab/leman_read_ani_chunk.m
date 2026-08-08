function [chunk, state] = leman_read_ani_chunk(fid, nLines, nChannels, state)
% Read up to nLines of a text .ani file into a channels-by-time matrix.
%
% The mex writes one line per time sample with nChannels space-separated
% floats. This reader keeps a persistent file position via fid.
%
% Parameters
% ----------
% fid :
%     Open file id for nerve_image.ani.
% nLines :
%     Maximum number of time lines to read.
% nChannels :
%     Expected floats per line (default 40).
% state :
%     Opaque state from a previous call, or [] at the start.
%
% Returns
% -------
% chunk :
%     [nChannels x nRead] double (nRead may be < nLines at EOF).
% state :
%     Updated state (.lines_read, .eof).

  if nargin < 4 || isempty(state)
    state = struct('lines_read', 0, 'eof', false);
  end
  if nLines < 1 || state.eof
    chunk = zeros(nChannels, 0);
    return
  end

  fmt = repmat('%f', 1, nChannels);
  raw = textscan(fid, fmt, nLines, 'CollectOutput', true);
  if isempty(raw) || isempty(raw{1})
    state.eof = true;
    chunk = zeros(nChannels, 0);
    return
  end

  data = raw{1};
  n_read = size(data, 1);
  if size(data, 2) ~= nChannels
    error( ...
      'leman_read_ani_chunk: expected %d columns, got %d', ...
      nChannels, size(data, 2));
  end
  chunk = data.';  % channels x time
  state.lines_read = state.lines_read + n_read;
  if n_read < nLines
    state.eof = true;
  end
end

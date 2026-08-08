function [ani, aniFreq, filterFreqs] = leman_calc_ani_streamed( ...
    inSignal, inSampleFreq, varargin)
% Drop-in streaming stand-in for IPEMCalcANI (spool + block-read).
%
% Still materialises the final downsampled ANI matrix (same as IPEMCalcANI
% output). Use leman_ani_from_spool_chunk directly to keep memory bounded.

  p = inputParser;
  addParameter(p, 'WorkDir', tempname, @(s) ischar(s) || isstring(s));
  addParameter(p, 'DownsamplingFactor', 4, @(x) isnumeric(x) && isscalar(x));
  addParameter(p, 'NumOfChannels', 40, @(x) isnumeric(x) && isscalar(x));
  addParameter(p, 'FirstCBU', 2.0, @(x) isnumeric(x) && isscalar(x));
  addParameter(p, 'CBUStep', 0.5, @(x) isnumeric(x) && isscalar(x));
  addParameter(p, 'ChunkLen', 1024, @(x) isnumeric(x) && isscalar(x));
  addParameter(p, 'Cleanup', true, @(x) islogical(x) && isscalar(x));
  parse(p, varargin{:});
  opts = p.Results;

  work_dir = char(opts.WorkDir);
  own_dir = false;
  if exist(work_dir, 'dir') ~= 7
    mkdir(work_dir);
    own_dir = true;
  end
  cleanup_obj = [];
  if opts.Cleanup
    cleanup_obj = onCleanup(@() cleanup_work(work_dir, own_dir)); %#ok<NASGU>
  end

  meta = leman_calc_ani_spool(inSignal, inSampleFreq, work_dir, ...
    'DownsamplingFactor', opts.DownsamplingFactor, ...
    'NumOfChannels', opts.NumOfChannels, ...
    'FirstCBU', opts.FirstCBU, ...
    'CBUStep', opts.CBUStep);

  parts = {};
  state = [];
  while true
    [chunk, state] = leman_ani_from_spool_chunk(meta, opts.ChunkLen, state);
    if isempty(chunk)
      break
    end
    parts{end + 1} = chunk; %#ok<AGROW>
    if state.eof
      break
    end
  end

  if isempty(parts)
    ani = zeros(meta.n_channels, 0);
  else
    ani = [parts{:}];
  end
  aniFreq = meta.final_sample_freq;
  filterFreqs = meta.filter_freqs;
end

function cleanup_work(work_dir, own_dir)
  if own_dir && exist(work_dir, 'dir') == 7
    rmdir(work_dir, 's');
  else
    for name = {'nerve_image.ani', 'FilterFrequencies.txt'}
      path = fullfile(work_dir, name{1});
      if exist(path, 'file') == 2
        delete(path);
      end
    end
  end
end

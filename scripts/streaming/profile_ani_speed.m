function report = profile_ani_speed(varargin)
% Compare wall time: IPEMCalcANI vs spool + block-read downsample (+ PP).
%
% Usage (MATLAB -batch):
%   profile_ani_speed('ToolboxDir', '/path/to/IPEMToolbox', ...
%                     'Durations', [5 30], 'OutFile', 'out.json')

  p = inputParser;
  addParameter(p, 'ToolboxDir', '', @(s) ischar(s) || isstring(s));
  addParameter(p, 'Durations', [5, 30], @(x) isnumeric(x) && isvector(x));
  addParameter(p, 'ChunkLen', 1024, @(x) isnumeric(x) && isscalar(x));
  addParameter(p, 'OutFile', '', @(s) ischar(s) || isstring(s));
  addParameter(p, 'Repeats', 1, @(x) isnumeric(x) && isscalar(x));
  parse(p, varargin{:});
  opts = p.Results;

  toolbox_dir = char(opts.ToolboxDir);
  if isempty(toolbox_dir)
    error('profile_ani_speed: ToolboxDir is required');
  end
  setup_ipem(toolbox_dir);

  this_dir = fileparts(mfilename('fullpath'));
  repo_root = fileparts(fileparts(this_dir));
  addpath(fullfile(repo_root, 'docker', 'matlab'));

  fs = 22050;
  durations = opts.Durations(:)';
  rows = cell(numel(durations), 1);

  for i = 1:numel(durations)
    dur = durations(i);
    t = (0:round(fs * dur) - 1) / fs;
    signal = 0.2 * sin(2 * pi * 440 * t);

    batch_times = zeros(1, opts.Repeats);
    stream_times = zeros(1, opts.Repeats);
    batch_pp_times = zeros(1, opts.Repeats);
    stream_pp_times = zeros(1, opts.Repeats);
    n_ani = nan;
    n_pp = nan;

    for r = 1:opts.Repeats
      tic;
      [ani, ani_freq] = IPEMCalcANI(signal, fs);
      batch_times(r) = toc;
      n_ani = size(ani, 2);

      tic;
      [pp, ~] = IPEMPeriodicityPitch(ani, ani_freq);
      batch_pp_times(r) = toc;
      n_pp = size(pp, 2);
      clear ani pp;

      work_dir = tempname;
      mkdir(work_dir);
      cleanup = onCleanup(@() rmdir(work_dir, 's')); %#ok<NASGU>

      tic;
      meta = leman_calc_ani_spool(signal, fs, work_dir);
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
      stream_ani = [parts{:}]; %#ok<NASGU>
      stream_times(r) = toc;
      clear stream_ani parts;

      % Fresh spool for PP-from-spool (fair: includes mex again).
      work_dir2 = tempname;
      mkdir(work_dir2);
      cleanup2 = onCleanup(@() rmdir(work_dir2, 's')); %#ok<NASGU>
      tic;
      meta2 = leman_calc_ani_spool(signal, fs, work_dir2);
      [stream_pp, ~] = leman_periodicity_pitch_from_spool(meta2, opts.ChunkLen);
      stream_pp_times(r) = toc;
      clear stream_pp;
    end

    row = struct( ...
      'duration_sec', dur, ...
      'n_ani_cols', n_ani, ...
      'n_pp_frames', n_pp, ...
      'batch_ani_sec', mean(batch_times), ...
      'stream_ani_sec', mean(stream_times), ...
      'batch_ani_pp_sec', mean(batch_times + batch_pp_times), ...
      'stream_ani_pp_sec', mean(stream_pp_times), ...
      'ani_speedup', mean(batch_times) / mean(stream_times), ...
      'ani_pp_speedup', mean(batch_times + batch_pp_times) / mean(stream_pp_times));
    rows{i} = row;
    fprintf(1, [ ...
      'audio=%.1fs batch_ani=%.3fs stream_ani=%.3fs (%.2fx) ', ...
      'batch_ani+pp=%.3fs stream_spool+pp=%.3fs (%.2fx)\n'], ...
      dur, row.batch_ani_sec, row.stream_ani_sec, row.ani_speedup, ...
      row.batch_ani_pp_sec, row.stream_ani_pp_sec, row.ani_pp_speedup);
  end

  report = struct( ...
    'chunk_len', opts.ChunkLen, ...
    'repeats', opts.Repeats, ...
    'cases', [rows{:}]);

  if ~isempty(opts.OutFile)
    payload = jsonencode(report);
    fid = fopen(char(opts.OutFile), 'w');
    fwrite(fid, payload);
    fclose(fid);
  end
end

function setup_ipem(toolbox_dir)
  addpath(toolbox_dir);
  octave_compat = fullfile(toolbox_dir, 'OctaveCompat');
  if exist(octave_compat, 'dir')
    addpath(octave_compat);
  end
  old = cd(toolbox_dir);
  cleanup = onCleanup(@() cd(old)); %#ok<NASGU>
  IPEMSetup;
end

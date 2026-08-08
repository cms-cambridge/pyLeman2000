function report = profile_path_memory(varargin)
% Compare memory stages for batch vs spool ANI→PP→contextuality paths.
%
% Run one mode per MATLAB process so RSS is not polluted by the other path.
%
% Usage:
%   profile_path_memory('ToolboxDir', ..., 'InputFile', ..., ...
%                       'Mode', 'batch'|'spool', 'OutFile', ...)

  p = inputParser;
  addParameter(p, 'ToolboxDir', '', @(s) ischar(s) || isstring(s));
  addParameter(p, 'InputFile', '', @(s) ischar(s) || isstring(s));
  addParameter(p, 'OutFile', '', @(s) ischar(s) || isstring(s));
  addParameter(p, 'Mode', 'spool', @(s) ischar(s) || isstring(s));
  addParameter(p, 'LocalDecaySec', 0.1, @(x) isnumeric(x) && isscalar(x));
  addParameter(p, 'GlobalDecaySec', 1.0, @(x) isnumeric(x) && isscalar(x));
  addParameter(p, 'ChunkLen', 1024, @(x) isnumeric(x) && isscalar(x));
  parse(p, varargin{:});
  opts = p.Results;

  toolbox_dir = char(opts.ToolboxDir);
  input_file = char(opts.InputFile);
  out_file = char(opts.OutFile);
  mode = lower(char(opts.Mode));
  if isempty(toolbox_dir) || isempty(input_file)
    error('profile_path_memory: ToolboxDir and InputFile are required');
  end
  if ~ismember(mode, {'batch', 'spool'})
    error('profile_path_memory: Mode must be batch or spool');
  end

  this_dir = fileparts(mfilename('fullpath'));
  repo_root = fileparts(fileparts(this_dir));
  addpath(fullfile(repo_root, 'docker', 'matlab'));
  setup_ipem(toolbox_dir);

  stages = {};
  stages{end + 1} = sample('after_setup');

  [in_dir, in_key, in_ext] = fileparts(input_file);
  [s, fs] = IPEMReadSoundFile(strcat(in_key, in_ext), in_dir);
  if size(s, 1) == 2
    s = (s(1, :) + s(2, :)) / 2;
  end
  audio_length_sec = numel(s) / fs;
  stages{end + 1} = sample('after_read_wav', ...
    'audio_length_sec', audio_length_sec, ...
    'wav_samples', numel(s));

  if strcmp(mode, 'batch')
    stages = run_batch(s, fs, opts, stages);
  else
    stages = run_spool(s, fs, opts, stages);
  end

  report = struct();
  report.mode = mode;
  report.input_file = input_file;
  report.audio_length_sec = audio_length_sec;
  report.sample_rate = fs;
  report.chunk_len = opts.ChunkLen;
  report.stages = normalize_stages(stages);
  report.peak_rss_mb = max([report.stages.rss_mb]);
  report.peak_pss_mb = max([report.stages.pss_mb]);
  report.baseline_pss_mb = report.stages(1).pss_mb;
  report.delta_peak_pss_mb = report.peak_pss_mb - report.baseline_pss_mb;

  fprintf(1, [ ...
    'PATH_MEM mode=%s audio=%.3fs peak_rss=%.1fMB peak_pss=%.1fMB ', ...
    'baseline_pss=%.1fMB delta_pss=%.1fMB\n'], ...
    mode, audio_length_sec, report.peak_rss_mb, report.peak_pss_mb, ...
    report.baseline_pss_mb, report.delta_peak_pss_mb);
  for i = 1:numel(report.stages)
    st = report.stages(i);
    fprintf(1, '  %-32s rss=%8.1fMB pss=%8.1fMB\n', ...
      st.name, st.rss_mb, st.pss_mb);
  end

  if ~isempty(out_file)
    payload = jsonencode(report);
    fid = fopen(out_file, 'w');
    fwrite(fid, payload);
    fclose(fid);
  end
end

function stages = run_batch(s, fs, opts, stages)
  [ANI, ANIFreq] = IPEMCalcANI(s, fs);
  stages{end + 1} = sample('after_calc_ani', ...
    'ani_size', size(ANI), 'bytes_est', numel(ANI) * 8);
  clear s;
  stages{end + 1} = sample('after_clear_wav');

  [PP, PPFreq, PPPeriods, PPFANI] = IPEMPeriodicityPitch(ANI, ANIFreq);
  stages{end + 1} = sample('after_periodicity_pitch', ...
    'pp_size', size(PP), 'ppfani_size', size(PPFANI), ...
    'bytes_est', numel(ANI) * 8 + numel(PP) * 8 + numel(PPFANI) * 8);
  clear ANI;
  stages{end + 1} = sample('after_clear_ani');

  [~, ~, ~, ~, running_corr] = IPEMContextualityIndex( ...
    PP, PPFreq, PPPeriods, [], ...
    opts.LocalDecaySec, opts.GlobalDecaySec, 0, 0); %#ok<ASGLU>
  stages{end + 1} = sample('after_contextuality', ...
    'corr_len', numel(running_corr));
  clear PPFANI PP running_corr;
  stages{end + 1} = sample('after_clear_all');
end

function stages = run_spool(s, fs, opts, stages)
  work_dir = tempname;
  mkdir(work_dir);
  cleanup = onCleanup(@() rmdir(work_dir, 's')); %#ok<NASGU>

  meta = leman_calc_ani_spool(s, fs, work_dir);
  ani_bytes = nan;
  if exist(meta.ani_path, 'file') == 2
    d = dir(meta.ani_path);
    ani_bytes = d.bytes;
  end
  stages{end + 1} = sample('after_ani_spool', ...
    'ani_file_bytes', ani_bytes, ...
    'trim_cols', meta.trim_cols);
  clear s;
  stages{end + 1} = sample('after_clear_wav');

  [PP, pp_state] = leman_periodicity_pitch_from_spool(meta, opts.ChunkLen);
  stages{end + 1} = sample('after_spool_pp', ...
    'pp_size', size(PP), 'bytes_est', numel(PP) * 8);

  corr = leman_contextuality_comparison_stream( ...
    PP, pp_state.out_sample_freq, ...
    opts.LocalDecaySec, opts.GlobalDecaySec, opts.ChunkLen);
  stages{end + 1} = sample('after_spool_contextuality', ...
    'corr_len', numel(corr), ...
    'bytes_est', numel(PP) * 8 + numel(corr) * 8);
  clear PP pp_state corr;
  stages{end + 1} = sample('after_clear_all');
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

function stage = sample(name, varargin)
  mem = read_proc_mem();
  stage = struct( ...
    'name', name, ...
    'rss_mb', mem.rss_mb, ...
    'pss_mb', mem.pss_mb, ...
    'timestamp', char(datetime('now', 'TimeZone', 'UTC', ...
      'Format', 'yyyy-MM-dd''T''HH:mm:ss.SSSSSS''Z''')));
  for i = 1:2:numel(varargin)
    stage.(varargin{i}) = varargin{i + 1};
  end
end

function stages = normalize_stages(cells)
  json_stages = cell(size(cells));
  for i = 1:numel(cells)
    st = cells{i};
    info = struct();
    core = {'name', 'rss_mb', 'pss_mb', 'timestamp'};
    fields = fieldnames(st);
    for f = 1:numel(fields)
      key = fields{f};
      if ~ismember(key, core)
        info.(key) = st.(key);
      end
    end
    json_stages{i} = struct( ...
      'name', st.name, ...
      'rss_mb', st.rss_mb, ...
      'pss_mb', st.pss_mb, ...
      'timestamp', st.timestamp, ...
      'info', info);
  end
  stages = [json_stages{:}];
end

function mem = read_proc_mem()
  rss_kb = nan;
  fid = fopen('/proc/self/status', 'r');
  if fid >= 0
    while true
      line = fgetl(fid);
      if ~ischar(line)
        break
      end
      if strncmp(line, 'VmRSS:', 6)
        parts = sscanf(line, 'VmRSS: %f');
        if ~isempty(parts)
          rss_kb = parts(1);
        end
        break
      end
    end
    fclose(fid);
  end

  pss_kb = nan;
  fid = fopen('/proc/self/smaps_rollup', 'r');
  if fid >= 0
    while true
      line = fgetl(fid);
      if ~ischar(line)
        break
      end
      if strncmp(line, 'Pss:', 4)
        parts = sscanf(line, 'Pss: %f');
        if ~isempty(parts)
          pss_kb = parts(1);
        end
        break
      end
    end
    fclose(fid);
  end

  mem = struct('rss_mb', rss_kb / 1024, 'pss_mb', pss_kb / 1024);
end

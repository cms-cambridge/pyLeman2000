function report = profile_stage_memory(varargin)
% Profile RSS/PSS after each Leman (2000) stage for one WAV.
%
% Usage:
%   report = profile_stage_memory( ...
%       'ToolboxDir', '/path/to/IPEMToolbox', ...
%       'InputFile', '/path/to/audio.wav', ...
%       'OutFile', '/tmp/profile.json')

  p = inputParser;
  addParameter(p, 'ToolboxDir', '', @(s) ischar(s) || isstring(s));
  addParameter(p, 'InputFile', '', @(s) ischar(s) || isstring(s));
  addParameter(p, 'OutFile', '', @(s) ischar(s) || isstring(s));
  addParameter(p, 'LocalDecaySec', 0.1, @(x) isnumeric(x) && isscalar(x));
  addParameter(p, 'GlobalDecaySec', 1.0, @(x) isnumeric(x) && isscalar(x));
  addParameter(p, 'AlsoStream', true, @(x) islogical(x) || isnumeric(x));
  parse(p, varargin{:});
  opts = p.Results;

  toolbox_dir = char(opts.ToolboxDir);
  input_file = char(opts.InputFile);
  out_file = char(opts.OutFile);
  if isempty(toolbox_dir) || isempty(input_file)
    error('profile_stage_memory: ToolboxDir and InputFile are required');
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
    'wav_samples', numel(s), ...
    'bytes_est', numel(s) * 8);

  [ANI, ANIFreq, ANIFilterFreqs] = IPEMCalcANI(s, fs); %#ok<ASGLU>
  stages{end + 1} = sample('after_calc_ani', ...
    'ani_size', size(ANI), ...
    'ani_freq', ANIFreq, ...
    'bytes_est', numel(ANI) * 8);

  clear s;
  stages{end + 1} = sample('after_clear_wav', ...
    'ani_size', size(ANI), ...
    'bytes_est', numel(ANI) * 8);

  if opts.AlsoStream
    [pp_stream, pp_state] = leman_periodicity_pitch_stream(ANI, ANIFreq, 256);
    stages{end + 1} = sample('after_stream_pp', ...
      'pp_size', size(pp_stream), ...
      'bytes_est', numel(ANI) * 8 + numel(pp_stream) * 8);

    corr_stream = leman_contextuality_comparison_stream( ...
      pp_stream, pp_state.out_sample_freq, ...
      opts.LocalDecaySec, opts.GlobalDecaySec, 256);
    stages{end + 1} = sample('after_stream_contextuality', ...
      'corr_len', numel(corr_stream), ...
      'bytes_est', numel(ANI) * 8 + numel(pp_stream) * 8 + numel(corr_stream) * 8);

    clear pp_stream pp_state corr_stream;
    stages{end + 1} = sample('after_clear_stream_outputs', ...
      'ani_size', size(ANI), ...
      'bytes_est', numel(ANI) * 8);
  end

  [PP, PPFreq, PPPeriods, PPFANI] = IPEMPeriodicityPitch(ANI, ANIFreq);
  stages{end + 1} = sample('after_periodicity_pitch', ...
    'pp_size', size(PP), ...
    'ppfani_size', size(PPFANI), ...
    'bytes_est', numel(ANI) * 8 + numel(PP) * 8 + numel(PPFANI) * 8);

  clear ANI ANIFilterFreqs;
  stages{end + 1} = sample('after_clear_ani', ...
    'pp_size', size(PP), ...
    'ppfani_size', size(PPFANI), ...
    'bytes_est', numel(PP) * 8 + numel(PPFANI) * 8);

  [~, ~, ~, ~, running_corr] = IPEMContextualityIndex( ...
    PP, PPFreq, PPPeriods, [], ...
    opts.LocalDecaySec, opts.GlobalDecaySec, 0, 0);
  stages{end + 1} = sample('after_contextuality', ...
    'corr_len', numel(running_corr), ...
    'bytes_est', numel(PP) * 8 + numel(PPFANI) * 8 + numel(running_corr) * 8);

  clear PPFANI;
  stages{end + 1} = sample('after_clear_ppfani', ...
    'pp_size', size(PP), ...
    'corr_len', numel(running_corr), ...
    'bytes_est', numel(PP) * 8 + numel(running_corr) * 8);

  clear PP PPPeriods running_corr;
  stages{end + 1} = sample('after_clear_all');

  report = struct();
  report.input_file = input_file;
  report.audio_length_sec = audio_length_sec;
  report.sample_rate = fs;
  report.local_decay_sec = opts.LocalDecaySec;
  report.global_decay_sec = opts.GlobalDecaySec;
  report.stages = stages;
  rss_vals = cellfun(@(st) st.rss_mb, stages);
  pss_vals = cellfun(@(st) st.pss_mb, stages);
  report.peak_rss_mb = max(rss_vals);
  report.peak_pss_mb = max(pss_vals);

  fprintf(1, 'PROFILE audio=%.3fs peak_rss=%.1fMB peak_pss=%.1fMB\n', ...
    audio_length_sec, report.peak_rss_mb, report.peak_pss_mb);
  for i = 1:numel(stages)
    st = stages{i};
    fprintf(1, '  %-28s rss=%8.1fMB pss=%8.1fMB\n', ...
      st.name, st.rss_mb, st.pss_mb);
  end

  if ~isempty(out_file)
    % Normalise stage fields for JSON: keep extras under info.
    json_stages = cell(size(stages));
    for i = 1:numel(stages)
      st = stages{i};
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
    json_report = report;
    json_report.stages = [json_stages{:}];
    payload = jsonencode(json_report);
    fid = fopen(out_file, 'w');
    if fid < 0
      error('profile_stage_memory: could not write %s', out_file);
    end
    fwrite(fid, payload);
    fclose(fid);
  end
end

function setup_ipem(toolbox_dir)
  if exist(fullfile(toolbox_dir, 'IPEMSetup.m'), 'file') ~= 2
    error('profile_stage_memory: IPEMSetup.m not found in %s', toolbox_dir);
  end
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
    'timestamp', char(datetime('now', 'TimeZone', 'UTC', 'Format', 'yyyy-MM-dd''T''HH:mm:ss.SSSSSS''Z''')));
  for i = 1:2:numel(varargin)
    stage.(varargin{i}) = varargin{i + 1};
  end
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
  elseif isnan(pss_kb)
    % Fall back to summing smaps if rollup is unavailable.
    pss_kb = sum_smaps_pss_kb();
  end

  mem = struct( ...
    'rss_mb', rss_kb / 1024, ...
    'pss_mb', pss_kb / 1024);
end

function total = sum_smaps_pss_kb()
  total = nan;
  fid = fopen('/proc/self/smaps', 'r');
  if fid < 0
    return
  end
  total = 0;
  while true
    line = fgetl(fid);
    if ~ischar(line)
      break
    end
    if strncmp(line, 'Pss:', 4)
      parts = sscanf(line, 'Pss: %f');
      if ~isempty(parts)
        total = total + parts(1);
      end
    end
  end
  fclose(fid);
end

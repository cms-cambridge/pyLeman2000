function report = profile_mex_memory(varargin)
% Profile memory around IPEMProcessAuditoryModelSafe only (no textread).
%
% Handshake with an external sampler:
%   1. Write PidFile and StatusFile='ready_for_mex'
%   2. Wait until GoFile exists
%   3. Run the mex
%   4. Write StatusFile='mex_done' and the JSON report

  p = inputParser;
  addParameter(p, 'ToolboxDir', '', @(s) ischar(s) || isstring(s));
  addParameter(p, 'InputFile', '', @(s) ischar(s) || isstring(s));
  addParameter(p, 'OutFile', '', @(s) ischar(s) || isstring(s));
  addParameter(p, 'PidFile', '', @(s) ischar(s) || isstring(s));
  addParameter(p, 'GoFile', '', @(s) ischar(s) || isstring(s));
  addParameter(p, 'StatusFile', '', @(s) ischar(s) || isstring(s));
  parse(p, varargin{:});
  opts = p.Results;

  toolbox_dir = char(opts.ToolboxDir);
  input_file = char(opts.InputFile);
  out_file = char(opts.OutFile);
  pid_file = char(opts.PidFile);
  go_file = char(opts.GoFile);
  status_file = char(opts.StatusFile);
  if isempty(toolbox_dir) || isempty(input_file)
    error('profile_mex_memory: ToolboxDir and InputFile are required');
  end

  setup_ipem(toolbox_dir);
  work_dir = tempname;
  mkdir(work_dir);
  cleanup = onCleanup(@() rmdir(work_dir, 's')); %#ok<NASGU>

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

  % Match IPEMCalcANI prep: resample to 22050, pad 20 ms, write input.wav.
  new_fs = 22050;
  n_zeros = round(0.020 / (1 / new_fs));
  the_zeros = zeros(1, n_zeros);
  if fs ~= new_fs
    new_sound = [the_zeros, resample(s, new_fs, fs), the_zeros];
  else
    new_sound = [the_zeros, s, the_zeros];
  end
  clear s;
  stages{end + 1} = sample('after_resample_pad', ...
    'resampled_samples', numel(new_sound));

  old = cd(work_dir);
  restore_dir = onCleanup(@() cd(old)); %#ok<NASGU>
  wavwrite(new_sound, new_fs, 16, 'input.wav');
  clear new_sound;
  stages{end + 1} = sample('after_write_input_wav');

  if ~isempty(pid_file)
    fid = fopen(pid_file, 'w');
    fprintf(fid, '%d\n', feature('getpid'));
    fclose(fid);
  end
  write_status(status_file, 'ready_for_mex');

  if ~isempty(go_file)
    deadline = datetime('now') + seconds(120);
    while exist(go_file, 'file') ~= 2
      if datetime('now') > deadline
        error('profile_mex_memory: timed out waiting for GoFile');
      end
      pause(0.05);
    end
  end

  stages{end + 1} = sample('before_mex');
  result = IPEMProcessAuditoryModel( ...
    'input.wav', '', 'nerve_image.ani', '', new_fs, 40, 2.0, 0.5);
  if result ~= 0
    error('profile_mex_memory: IPEMProcessAuditoryModel returned %d', result);
  end
  stages{end + 1} = sample('after_mex_before_textread');

  % Inspect on-disk ANI size without loading it.
  ani_bytes = nan;
  if exist('nerve_image.ani', 'file') == 2
    d = dir('nerve_image.ani');
    ani_bytes = d.bytes;
  end
  stages{end + 1} = sample('after_stat_ani_file', 'ani_file_bytes', ani_bytes);

  write_status(status_file, 'mex_done');

  report = struct();
  report.input_file = input_file;
  report.audio_length_sec = audio_length_sec;
  report.sample_rate = fs;
  report.ani_file_bytes = ani_bytes;
  report.pid = feature('getpid');
  report.stages = normalize_stages(stages);
  report.peak_rss_mb = max([report.stages.rss_mb]);
  report.peak_pss_mb = max([report.stages.pss_mb]);

  fprintf(1, 'MEX_PROFILE audio=%.3fs peak_rss=%.1fMB peak_pss=%.1fMB ani_file=%.1fMB\n', ...
    audio_length_sec, report.peak_rss_mb, report.peak_pss_mb, ani_bytes / 1024 / 1024);
  for i = 1:numel(report.stages)
    st = report.stages(i);
    fprintf(1, '  %-28s rss=%8.1fMB pss=%8.1fMB\n', st.name, st.rss_mb, st.pss_mb);
  end

  if ~isempty(out_file)
    payload = jsonencode(report);
    fid = fopen(out_file, 'w');
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

function write_status(path, value)
  if isempty(path)
    return
  end
  fid = fopen(path, 'w');
  fprintf(fid, '%s\n', value);
  fclose(fid);
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

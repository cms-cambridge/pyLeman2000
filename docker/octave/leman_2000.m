function leman_2000(in_file, out_file, local_decay_sec, global_decay_sec, detail)
% Octave implementation of Leman (2000) for the pyLeman2000 Docker backend.
%
% Writes JSON with top-level fields:
%   audio_length_sec, num_channels, sample_rate,
%   local_global_comparison[{local_decay_sec, global_decay_sec, running_correlation}],
%   and optionally auditory_nerve / periodicity_pitch when detail > 1.
%
% For detail <= 1, ANI is disk-spooled and periodicity pitch is chunked
% (same strategy as docker/matlab/leman_2000_compute.m).

  pkg load signal;

  toolbox_dir = '/opt/IPEMToolbox/IPEMToolbox';
  addpath(toolbox_dir);
  addpath('/opt/pyleman_helpers');
  cd(toolbox_dir);
  IPEMSetup;

  [in_dir, in_file_key, in_file_ext] = fileparts(in_file);
  in_file_name = strcat(in_file_key, in_file_ext);
  [s, fs] = IPEMReadSoundFile(in_file_name, in_dir);
  num_channels = size(s, 1);

  local_decay_sec = parse_array(local_decay_sec);
  global_decay_sec = parse_array(global_decay_sec);
  detail = parse_scalar(detail);

  if (num_channels == 2)
    s = (s(1, :) + s(2, :)) / 2;
  end

  audio_length_sec = length(s) / fs;

  res = struct();
  res.audio_length_sec = audio_length_sec;
  res.num_channels = num_channels;
  res.sample_rate = fs;

  if (detail > 1)
    [ANI, ANIFreq, ANIFilterFreqs] = IPEMCalcANI(s, fs);
    clear s;
    [PP, PPFreq, PPPeriods, PPFANI] = IPEMPeriodicityPitch(ANI, ANIFreq);
    res.auditory_nerve = struct( ...
      'images', ANI, ...
      'sample_freq', ANIFreq, ...
      'filter_freqs', ANIFilterFreqs);
    res.periodicity_pitch = struct( ...
      'signal', PP, ...
      'sample_freq', PPFreq, ...
      'pitch_periods', PPPeriods, ...
      'filtered_auditory_nerve_images', PPFANI);
    clear ANI ANIFilterFreqs PPFANI;
  else
    work_dir = tempname;
    mkdir(work_dir);
    cleanup = onCleanup(@() rmdir_if_present(work_dir)); %#ok<NASGU>
    meta = leman_calc_ani_spool(s, fs, work_dir);
    clear s;
    [PP, pp_state] = leman_periodicity_pitch_from_spool(meta, 1024);
    PPFreq = pp_state.out_sample_freq;
    PPPeriods = pp_state.out_periods;
  end

  % Match MATLAB combvec(local, global): local varies fastest.
  n_local = numel(local_decay_sec);
  n_global = numel(global_decay_sec);
  n_combinations = n_local * n_global;
  comparisons = cell(n_combinations, 1);
  combo_idx = 0;
  for gi = 1:n_global
    for li = 1:n_local
      combo_idx = combo_idx + 1;
      local_decay = local_decay_sec(li);
      global_decay = global_decay_sec(gi);
      fprintf(1, 'Computing running correlation %d/%d...\n', combo_idx, n_combinations);
      [~, ~, ~, ~, running_corr] = IPEMContextualityIndex( ...
        PP, PPFreq, PPPeriods, [], local_decay, global_decay, [], 0);
      comparisons{combo_idx} = struct( ...
        'local_decay_sec', local_decay, ...
        'global_decay_sec', global_decay, ...
        'running_correlation', running_corr(:)');
    end
  end
  res.local_global_comparison = comparisons;

  payload = jsonencode(res);
  fid = fopen(out_file, 'w');
  if (fid < 0)
    error('leman_2000: could not open output file %s', out_file);
  end
  fwrite(fid, payload);
  fclose(fid);
end

function rmdir_if_present(path)
  if exist(path, 'dir') == 7
    rmdir(path, 's');
  end
end

function array = parse_array(x)
  if (ischar(x) || isstring(x))
    parts = strsplit(char(x), ',');
    array = zeros(1, numel(parts));
    for i = 1:numel(parts)
      array(i) = str2double(strtrim(parts{i}));
    end
  else
    array = x(:)';
  end
end

function value = parse_scalar(x)
  if (ischar(x) || isstring(x))
    value = str2double(char(x));
  else
    value = double(x);
  end
end

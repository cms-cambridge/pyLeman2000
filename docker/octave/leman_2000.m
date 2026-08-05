function leman_2000(in_file, out_file, local_decay_sec, global_decay_sec, detail)
% Octave implementation of Leman (2000) for the pyLeman2000 Docker backend.
%
% Writes JSON with top-level fields:
%   audio_length_sec, num_channels, sample_rate,
%   local_global_comparison[{local_decay_sec, global_decay_sec, running_correlation}],
%   and optionally auditory_nerve / periodicity_pitch when detail > 1.

  toolbox_dir = '/opt/IPEMToolbox/IPEMToolbox';
  addpath(toolbox_dir);
  cd(toolbox_dir);
  IPEMSetup;

  [in_dir, in_file_key, in_file_ext] = fileparts(in_file);
  in_file_name = strcat(in_file_key, in_file_ext);
  [s, fs] = IPEMReadSoundFile(in_file_name, in_dir);
  num_channels = size(s, 1);

  local_decay_sec = parse_array(local_decay_sec);
  global_decay_sec = parse_array(global_decay_sec);

  if (num_channels == 2)
    s = (s(1, :) + s(2, :)) / 2;
  end

  audio_length_sec = length(s) / fs;

  [ANI, ANIFreq, ANIFilterFreqs] = IPEMCalcANI(s, fs);
  [PP, PPFreq, PPPeriods, PPFANI] = IPEMPeriodicityPitch(ANI, ANIFreq);

  res = struct();
  res.audio_length_sec = audio_length_sec;
  res.num_channels = num_channels;
  res.sample_rate = fs;

  if (detail > 1)
    res.auditory_nerve = struct( ...
      'images', ANI, ...
      'sample_freq', ANIFreq, ...
      'filter_freqs', ANIFilterFreqs);
    res.periodicity_pitch = struct( ...
      'signal', PP, ...
      'sample_freq', PPFreq, ...
      'pitch_periods', PPPeriods, ...
      'filtered_auditory_nerve_images', PPFANI);
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

function report = run_ani_parity(varargin)
% Compare IPEMCalcANI against spool + block-read + stream downsample.
%
% Usage (MATLAB -batch):
%   report = run_ani_parity('ToolboxDir', '/path/to/IPEMToolbox')

  p = inputParser;
  addParameter(p, 'ToolboxDir', '', @(s) ischar(s) || isstring(s));
  addParameter(p, 'AbsTol', 1e-12, @(x) isnumeric(x) && isscalar(x));
  parse(p, varargin{:});
  opts = p.Results;

  toolbox_dir = char(opts.ToolboxDir);
  if isempty(toolbox_dir)
    error('run_ani_parity: ToolboxDir is required');
  end
  setup_ipem(toolbox_dir);

  this_dir = fileparts(mfilename('fullpath'));
  repo_root = fileparts(fileparts(this_dir));
  addpath(fullfile(repo_root, 'docker', 'matlab'));

  rng(3);
  fs = 22050;
  cases = {};
  cases{end + 1} = make_case('tone_0p3s', tone(fs, 0.3, 440), fs, [64, 256, 1024]);
  cases{end + 1} = make_case('noise_0p5s', randn(1, round(fs * 0.5)), fs, [100, 400]);
  cases{end + 1} = make_case('short_0p05s', tone(fs, 0.05, 880), fs, [32, 128]);

  results = cell(numel(cases), 1);
  overall_ok = true;
  overall_max = 0;

  for i = 1:numel(cases)
    c = cases{i};
    [full_ani, full_freq, full_filters] = IPEMCalcANI(c.signal, c.sample_freq);

    case_max = 0;
    chunk_rows = {};
    for k = 1:numel(c.chunk_lens)
      chunk_len = c.chunk_lens(k);
      work_dir = tempname;
      mkdir(work_dir);
      cleanup = onCleanup(@() rmdir(work_dir, 's')); %#ok<NASGU>

      meta = leman_calc_ani_spool(c.signal, c.sample_freq, work_dir);
      parts = {};
      state = [];
      while true
        [chunk, state] = leman_ani_from_spool_chunk(meta, chunk_len, state);
        if isempty(chunk)
          break
        end
        parts{end + 1} = chunk; %#ok<AGROW>
        if state.eof
          break
        end
      end
      if isempty(parts)
        stream_ani = zeros(meta.n_channels, 0);
      else
        stream_ani = [parts{:}];
      end

      diff_ani = max_abs_diff(full_ani, stream_ani);
      diff_freq = abs(full_freq - meta.final_sample_freq);
      diff_filt = max_abs_diff(full_filters(:), meta.filter_freqs(:));
      diff = max([diff_ani, diff_freq, diff_filt]);
      case_max = max(case_max, diff);
      chunk_rows{end + 1} = struct( ...
        'chunk_len', chunk_len, ...
        'max_abs_diff', diff, ...
        'ani_diff', diff_ani, ...
        'freq_diff', diff_freq, ...
        'filter_diff', diff_filt, ...
        'ok', diff <= opts.AbsTol); %#ok<AGROW>
      if diff > opts.AbsTol
        overall_ok = false;
      end
    end

    % Also check PP-from-spool against IPEMPeriodicityPitch(full_ani).
    [full_pp, full_pp_freq] = IPEMPeriodicityPitch(full_ani, full_freq);
    work_dir = tempname;
    mkdir(work_dir);
    cleanup2 = onCleanup(@() rmdir(work_dir, 's')); %#ok<NASGU>
    meta = leman_calc_ani_spool(c.signal, c.sample_freq, work_dir);
    [stream_pp, pp_state] = leman_periodicity_pitch_from_spool(meta, 256);
    diff_pp = max_abs_diff(full_pp, stream_pp);
    diff_pp_freq = abs(full_pp_freq - pp_state.out_sample_freq);
    pp_diff = max(diff_pp, diff_pp_freq);
    case_max = max(case_max, pp_diff);
    if pp_diff > opts.AbsTol
      overall_ok = false;
    end

    overall_max = max(overall_max, case_max);
    results{i} = struct( ...
      'name', c.name, ...
      'n_time_full', size(full_ani, 2), ...
      'max_abs_diff', case_max, ...
      'pp_max_abs_diff', pp_diff, ...
      'ok', case_max <= opts.AbsTol, ...
      'chunks', [chunk_rows{:}]);
    fprintf(1, '%s: max_abs_diff=%.3e pp=%.3e ok=%d\n', ...
      c.name, case_max, pp_diff, case_max <= opts.AbsTol);
  end

  report = struct( ...
    'ok', overall_ok, ...
    'max_abs_diff', overall_max, ...
    'abs_tol', opts.AbsTol, ...
    'cases', {results});

  if ~overall_ok
    error( ...
      'run_ani_parity: FAILED max_abs_diff=%.3e (tol=%.3e)', ...
      overall_max, opts.AbsTol);
  end
  fprintf(1, 'PARITY_OK max_abs_diff=%.3e tol=%.3e\n', overall_max, opts.AbsTol);
end

function setup_ipem(toolbox_dir)
  if exist(fullfile(toolbox_dir, 'IPEMSetup.m'), 'file') ~= 2
    error('run_ani_parity: IPEMSetup.m not found in %s', toolbox_dir);
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

function c = make_case(name, signal, sample_freq, chunk_lens)
  c = struct( ...
    'name', name, ...
    'signal', signal, ...
    'sample_freq', sample_freq, ...
    'chunk_lens', chunk_lens);
end

function s = tone(fs, dur, freq)
  t = (0:round(fs * dur) - 1) / fs;
  s = 0.2 * sin(2 * pi * freq * t);
end

function diff = max_abs_diff(a, b)
  if ~isequal(size(a), size(b))
    diff = inf;
    return
  end
  delta = abs(a(:) - b(:));
  both_nan = isnan(a(:)) & isnan(b(:));
  delta(both_nan) = 0;
  if isempty(delta)
    diff = 0;
  else
    diff = max(delta);
  end
end

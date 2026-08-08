function report = run_pipeline_parity(varargin)
% Compare full IPEM PP+contextuality against streamed PP+contextuality.
%
% Uses synthetic ANI input. Verifies that chaining
% leman_periodicity_pitch_stream into
% leman_contextuality_comparison_stream matches
% IPEMPeriodicityPitch + IPEMContextualityIndex.

  p = inputParser;
  addParameter(p, 'ToolboxDir', '', @(s) ischar(s) || isstring(s));
  addParameter(p, 'AbsTol', 1e-12, @(x) isnumeric(x) && isscalar(x));
  parse(p, varargin{:});
  opts = p.Results;

  toolbox_dir = char(opts.ToolboxDir);
  if isempty(toolbox_dir)
    error('run_pipeline_parity: ToolboxDir is required');
  end
  setup_ipem(toolbox_dir);

  this_dir = fileparts(mfilename('fullpath'));
  repo_root = fileparts(fileparts(this_dir));
  addpath(fullfile(repo_root, 'docker', 'matlab'));

  rng(2);
  ani_freq = 11025 / 4;
  cases = {};
  cases{end + 1} = make_case( ...
    'random_pipeline', randn(40, 1000), ani_freq, 0.1, 1.5, [1, 40, 175, 1000]);
  cases{end + 1} = make_case( ...
    'impulse_pipeline', impulse_ani(40, 600), ani_freq, 0.2, 2.0, [13, 200, 600]);

  results = cell(numel(cases), 1);
  overall_ok = true;
  overall_max = 0;

  for i = 1:numel(cases)
    c = cases{i};
    [full_pp, pp_freq] = IPEMPeriodicityPitch(c.ani, c.sample_freq);
    [~, ~, ~, ~, full_corr] = IPEMContextualityIndex( ...
      full_pp, pp_freq, [], [], c.local_decay_sec, c.global_decay_sec, 0, 0);
    full_corr = full_corr(:)';

    case_max = 0;
    chunk_rows = {};
    for k = 1:numel(c.chunk_lens)
      chunk_len = c.chunk_lens(k);
      [stream_pp, state] = leman_periodicity_pitch_stream( ...
        c.ani, c.sample_freq, chunk_len);
      stream_corr = leman_contextuality_comparison_stream( ...
        stream_pp, state.out_sample_freq, ...
        c.local_decay_sec, c.global_decay_sec, chunk_len);
      diff = max_abs_diff(full_corr, stream_corr);
      case_max = max(case_max, diff);
      chunk_rows{end + 1} = struct( ...
        'chunk_len', chunk_len, ...
        'max_abs_diff', diff, ...
        'ok', diff <= opts.AbsTol); %#ok<AGROW>
      if diff > opts.AbsTol
        overall_ok = false;
      end
    end
    overall_max = max(overall_max, case_max);
    results{i} = struct( ...
      'name', c.name, ...
      'n_time', size(c.ani, 2), ...
      'n_pp_frames', size(full_pp, 2), ...
      'max_abs_diff', case_max, ...
      'ok', case_max <= opts.AbsTol, ...
      'chunks', [chunk_rows{:}]);
    fprintf(1, '%s: max_abs_diff=%.3e ok=%d\n', ...
      c.name, case_max, case_max <= opts.AbsTol);
  end

  report = struct( ...
    'ok', overall_ok, ...
    'max_abs_diff', overall_max, ...
    'abs_tol', opts.AbsTol, ...
    'cases', {results});

  if ~overall_ok
    error( ...
      'run_pipeline_parity: FAILED max_abs_diff=%.3e (tol=%.3e)', ...
      overall_max, opts.AbsTol);
  end
  fprintf(1, 'PARITY_OK max_abs_diff=%.3e tol=%.3e\n', overall_max, opts.AbsTol);
end

function setup_ipem(toolbox_dir)
  if exist(fullfile(toolbox_dir, 'IPEMSetup.m'), 'file') ~= 2
    error('run_pipeline_parity: IPEMSetup.m not found in %s', toolbox_dir);
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

function c = make_case(name, ani, sample_freq, local_decay, global_decay, chunk_lens)
  c = struct( ...
    'name', name, ...
    'ani', ani, ...
    'sample_freq', sample_freq, ...
    'local_decay_sec', local_decay, ...
    'global_decay_sec', global_decay, ...
    'chunk_lens', chunk_lens);
end

function ani = impulse_ani(n_chan, n_time)
  ani = zeros(n_chan, n_time);
  ani(:, 1) = 1;
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

function report = run_contextuality_parity(varargin)
% Compare full-file IPEM contextuality #3 against chunked streaming.
%
% Usage (MATLAB -batch):
%   report = run_contextuality_parity('ToolboxDir', '/path/to/IPEMToolbox')
%
% Returns a struct with fields ok, max_abs_diff, cases.

  p = inputParser;
  addParameter(p, 'ToolboxDir', '', @(s) ischar(s) || isstring(s));
  addParameter(p, 'AbsTol', 1e-12, @(x) isnumeric(x) && isscalar(x));
  parse(p, varargin{:});
  opts = p.Results;

  toolbox_dir = char(opts.ToolboxDir);
  if isempty(toolbox_dir)
    error('run_contextuality_parity: ToolboxDir is required');
  end
  setup_ipem(toolbox_dir);

  this_dir = fileparts(mfilename('fullpath'));
  repo_root = fileparts(fileparts(this_dir));
  addpath(fullfile(repo_root, 'docker', 'matlab'));

  rng(0);
  cases = {};
  cases{end + 1} = make_case('impulse_64', impulse_pp(64, 96), 96, 0.1, 1.0, [1, 7, 16, 64]);
  cases{end + 1} = make_case('silence_128', zeros(64, 128), 98.4375, 0.1, 1.5, [1, 13, 50, 128]);
  cases{end + 1} = make_case( ...
    'random_pp_400', randn(706, 400), 98.4375, 0.1, 2.0, [1, 17, 64, 97, 400]);
  cases{end + 1} = make_case( ...
    'random_pp_decay_grid', randn(128, 250), 100, 0.2, 1.0, [3, 25, 101]);
  cases{end + 1} = make_case( ...
    'two_combos_shared_pp', randn(256, 180), 98.4375, 0.1, 1.0, [9, 60]);

  results = cell(numel(cases), 1);
  overall_ok = true;
  overall_max = 0;

  for i = 1:numel(cases)
    c = cases{i};
    full_corr = reference_contextuality( ...
      c.pp, c.sample_freq, c.local_decay_sec, c.global_decay_sec);
    case_max = 0;
    chunk_rows = {};
    for k = 1:numel(c.chunk_lens)
      chunk_len = c.chunk_lens(k);
      stream_corr = leman_contextuality_comparison_stream( ...
        c.pp, c.sample_freq, c.local_decay_sec, c.global_decay_sec, chunk_len);
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
      'n_periods', size(c.pp, 1), ...
      'n_time', size(c.pp, 2), ...
      'local_decay_sec', c.local_decay_sec, ...
      'global_decay_sec', c.global_decay_sec, ...
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
      'run_contextuality_parity: FAILED max_abs_diff=%.3e (tol=%.3e)', ...
      overall_max, opts.AbsTol);
  end
  fprintf(1, 'PARITY_OK max_abs_diff=%.3e tol=%.3e\n', overall_max, opts.AbsTol);
end

function setup_ipem(toolbox_dir)
  if exist(fullfile(toolbox_dir, 'IPEMSetup.m'), 'file') ~= 2
    error('run_contextuality_parity: IPEMSetup.m not found in %s', toolbox_dir);
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

function c = make_case(name, pp, sample_freq, local_decay, global_decay, chunk_lens)
  c = struct( ...
    'name', name, ...
    'pp', pp, ...
    'sample_freq', sample_freq, ...
    'local_decay_sec', local_decay, ...
    'global_decay_sec', global_decay, ...
    'chunk_lens', chunk_lens);
end

function pp = impulse_pp(n_periods, n_time)
  pp = zeros(n_periods, n_time);
  pp(:, 1) = 1;
end

function running_corr = reference_contextuality( ...
    pp, sample_freq, local_decay_sec, global_decay_sec)
  [~, ~, ~, ~, running_corr] = IPEMContextualityIndex( ...
    pp, sample_freq, [], [], local_decay_sec, global_decay_sec, 0, 0);
  running_corr = running_corr(:)';
end

function diff = max_abs_diff(a, b)
  if ~isequal(size(a), size(b))
    error( ...
      'run_contextuality_parity: size mismatch [%s] vs [%s]', ...
      num2str(size(a)), num2str(size(b)));
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

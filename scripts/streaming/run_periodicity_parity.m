function report = run_periodicity_parity(varargin)
% Compare full-file IPEMPeriodicityPitch against chunked streaming.
%
% Usage (MATLAB -batch):
%   report = run_periodicity_parity('ToolboxDir', '/path/to/IPEMToolbox')

  p = inputParser;
  addParameter(p, 'ToolboxDir', '', @(s) ischar(s) || isstring(s));
  addParameter(p, 'AbsTol', 1e-12, @(x) isnumeric(x) && isscalar(x));
  parse(p, varargin{:});
  opts = p.Results;

  toolbox_dir = char(opts.ToolboxDir);
  if isempty(toolbox_dir)
    error('run_periodicity_parity: ToolboxDir is required');
  end
  setup_ipem(toolbox_dir);

  this_dir = fileparts(mfilename('fullpath'));
  repo_root = fileparts(fileparts(this_dir));
  addpath(fullfile(repo_root, 'docker', 'matlab'));

  rng(1);
  ani_freq = 11025 / 4;  % default downsampled ANI rate
  cases = {};
  cases{end + 1} = make_case( ...
    'impulse_short', impulse_ani(40, 400), ani_freq, [1, 17, 64, 400]);
  cases{end + 1} = make_case( ...
    'silence', zeros(40, 500), ani_freq, [1, 50, 125, 500]);
  cases{end + 1} = make_case( ...
    'random_ani', randn(40, 1200), ani_freq, [1, 33, 97, 256, 1200]);
  cases{end + 1} = make_case( ...
    'few_channels', randn(8, 800), ani_freq, [7, 80, 800]);
  cases{end + 1} = make_case( ...
    'boundary_awkward', randn(40, 353), ani_freq, [1, 19, 176, 353]);

  results = cell(numel(cases), 1);
  overall_ok = true;
  overall_max = 0;

  for i = 1:numel(cases)
    c = cases{i};
    [full_pp, full_freq, full_periods, full_fani] = IPEMPeriodicityPitch( ...
      c.ani, c.sample_freq);
    case_max = 0;
    chunk_rows = {};
    for k = 1:numel(c.chunk_lens)
      chunk_len = c.chunk_lens(k);
      [stream_pp, state] = leman_periodicity_pitch_stream( ...
        c.ani, c.sample_freq, chunk_len);
      diffs = [ ...
        max_abs_diff(full_pp, stream_pp), ...
        abs(full_freq - state.out_sample_freq), ...
        max_abs_diff(full_periods(:), state.out_periods(:))];
      % FANI is not returned by the stream helper; reconstruct via one
      % full-chunk stream of the filter path is covered by PP agreement.
      diff = max(diffs);
      case_max = max(case_max, diff);
      chunk_rows{end + 1} = struct( ...
        'chunk_len', chunk_len, ...
        'max_abs_diff', diff, ...
        'n_frames_full', size(full_pp, 2), ...
        'n_frames_stream', size(stream_pp, 2), ...
        'ok', diff <= opts.AbsTol && isequal(size(full_pp), size(stream_pp))); %#ok<AGROW>
      if ~(diff <= opts.AbsTol && isequal(size(full_pp), size(stream_pp)))
        overall_ok = false;
      end
    end
    overall_max = max(overall_max, case_max);
    results{i} = struct( ...
      'name', c.name, ...
      'n_channels', size(c.ani, 1), ...
      'n_time', size(c.ani, 2), ...
      'n_frames', size(full_pp, 2), ...
      'fani_cols', size(full_fani, 2), ...
      'max_abs_diff', case_max, ...
      'ok', case_max <= opts.AbsTol, ...
      'chunks', [chunk_rows{:}]);
    fprintf(1, '%s: frames=%d max_abs_diff=%.3e ok=%d\n', ...
      c.name, size(full_pp, 2), case_max, case_max <= opts.AbsTol);
  end

  report = struct( ...
    'ok', overall_ok, ...
    'max_abs_diff', overall_max, ...
    'abs_tol', opts.AbsTol, ...
    'cases', {results});

  if ~overall_ok
    error( ...
      'run_periodicity_parity: FAILED max_abs_diff=%.3e (tol=%.3e)', ...
      overall_max, opts.AbsTol);
  end
  fprintf(1, 'PARITY_OK max_abs_diff=%.3e tol=%.3e\n', overall_max, opts.AbsTol);
end

function setup_ipem(toolbox_dir)
  if exist(fullfile(toolbox_dir, 'IPEMSetup.m'), 'file') ~= 2
    error('run_periodicity_parity: IPEMSetup.m not found in %s', toolbox_dir);
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

function c = make_case(name, ani, sample_freq, chunk_lens)
  c = struct( ...
    'name', name, ...
    'ani', ani, ...
    'sample_freq', sample_freq, ...
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

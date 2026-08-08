function report = run_compute_spool_parity(varargin)
% Compare detail=0 spool compute vs classic IPEMCalcANI→PP→contextuality.
%
% Usage:
%   run_compute_spool_parity('ToolboxDir', '/path/to/IPEMToolbox')

  p = inputParser;
  addParameter(p, 'ToolboxDir', '', @(s) ischar(s) || isstring(s));
  addParameter(p, 'AbsTol', 1e-12, @(x) isnumeric(x) && isscalar(x));
  addParameter(p, 'InputFile', '', @(s) ischar(s) || isstring(s));
  parse(p, varargin{:});
  opts = p.Results;

  toolbox_dir = char(opts.ToolboxDir);
  if isempty(toolbox_dir)
    error('run_compute_spool_parity: ToolboxDir is required');
  end
  setup_ipem(toolbox_dir);

  this_dir = fileparts(mfilename('fullpath'));
  repo_root = fileparts(fileparts(this_dir));
  addpath(fullfile(repo_root, 'docker', 'matlab'));

  input_file = char(opts.InputFile);
  own_wav = false;
  if isempty(input_file)
    input_file = fullfile(tempdir, sprintf('pyleman_spool_parity_%d.wav', feature('getpid')));
    fs = 22050;
    t = (0:round(fs * 0.4) - 1) / fs;
    s = 0.2 * sin(2 * pi * 440 * t);
    audiowrite(input_file, s(:), fs);
    own_wav = true;
  end
  cleanup = [];
  if own_wav
    cleanup = onCleanup(@() delete(input_file)); %#ok<NASGU>
  end

  local_decay = 0.1;
  global_decay = 1.5;

  % Reference: classic full-matrix path (same as former detail=0).
  [in_dir, in_key, in_ext] = fileparts(input_file);
  [s, fs] = IPEMReadSoundFile(strcat(in_key, in_ext), in_dir);
  if size(s, 1) == 2
    s = (s(1, :) + s(2, :)) / 2;
  end
  [ANI, ANIFreq] = IPEMCalcANI(s, fs);
  [PP, PPFreq, PPPeriods] = IPEMPeriodicityPitch(ANI, ANIFreq);
  [~, ~, ~, ~, ref_corr] = IPEMContextualityIndex( ...
    PP, PPFreq, PPPeriods, [], local_decay, global_decay, 0, 0);
  ref_corr = ref_corr(:)';

  res = leman_2000_compute(input_file, local_decay, global_decay, 0);
  got = res.local_global_comparison{1}.running_correlation;
  got = got(:)';

  diff = max_abs_diff(ref_corr, got);
  report = struct( ...
    'ok', diff <= opts.AbsTol, ...
    'max_abs_diff', diff, ...
    'abs_tol', opts.AbsTol, ...
    'n_corr', numel(ref_corr));

  fprintf(1, 'compute_spool: max_abs_diff=%.3e ok=%d\n', diff, report.ok);
  if ~report.ok
    error( ...
      'run_compute_spool_parity: FAILED max_abs_diff=%.3e (tol=%.3e)', ...
      diff, opts.AbsTol);
  end
  fprintf(1, 'PARITY_OK max_abs_diff=%.3e tol=%.3e\n', diff, opts.AbsTol);
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

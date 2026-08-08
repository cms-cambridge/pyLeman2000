function meta = leman_calc_ani_spool(inSignal, inSampleFreq, workDir, varargin)
% Run auditory-model mex and leave the .ani spool on disk (no textread).
%
% Mirrors the prep + mex portion of IPEMCalcANI, but keeps nerve_image.ani
% and FilterFrequencies.txt for block-reading / streaming downsample.
%
% Parameters
% ----------
% inSignal :
%     Mono row or column vector.
% inSampleFreq :
%     Sample rate of inSignal (Hz).
% workDir :
%     Directory for temporary wav / .ani files (created if missing).
% varargin :
%     Name-value: DownsamplingFactor (4), NumOfChannels (40), FirstCBU (2.0),
%     CBUStep (0.5).
%
% Returns
% -------
% meta :
%     Struct with ani_path, filter_freqs, raw_sample_freq, downsample_factor,
%     final_sample_freq, n_channels, trim_cols, work_dir.

  p = inputParser;
  addParameter(p, 'DownsamplingFactor', 4, @(x) isnumeric(x) && isscalar(x));
  addParameter(p, 'NumOfChannels', 40, @(x) isnumeric(x) && isscalar(x));
  addParameter(p, 'FirstCBU', 2.0, @(x) isnumeric(x) && isscalar(x));
  addParameter(p, 'CBUStep', 0.5, @(x) isnumeric(x) && isscalar(x));
  parse(p, varargin{:});
  opts = p.Results;

  if isempty(inSignal) || isempty(inSampleFreq)
    error('leman_calc_ani_spool: signal and sample frequency are required');
  end
  if size(inSignal, 1) ~= 1
    if size(inSignal, 2) ~= 1
      error('leman_calc_ani_spool: mono signals only');
    end
    inSignal = inSignal.';
  end

  workDir = char(workDir);
  if exist(workDir, 'dir') ~= 7
    mkdir(workDir);
  end

  new_fs = 22050;
  n_zeros = round(0.020 / (1 / new_fs));
  the_zeros = zeros(1, n_zeros);
  if inSampleFreq ~= new_fs
    new_sound = [the_zeros, resample(inSignal, new_fs, inSampleFreq), the_zeros];
  else
    new_sound = [the_zeros, inSignal, the_zeros];
  end

  old = cd(workDir);
  restore_dir = onCleanup(@() cd(old)); %#ok<NASGU>
  wavwrite(new_sound, new_fs, 16, 'input.wav');
  clear new_sound;

  result = IPEMProcessAuditoryModel( ...
    'input.wav', '', 'nerve_image.ani', '', ...
    new_fs, opts.NumOfChannels, opts.FirstCBU, opts.CBUStep);
  if result ~= 0
    error('leman_calc_ani_spool: IPEMProcessAuditoryModel returned %d', result);
  end

  filter_freqs = dlmread('FilterFrequencies.txt', ' ');
  filter_freqs = 1000 * filter_freqs(:);

  % Best-effort cleanup of mex side files; keep .ani and filter freqs.
  for name = {'decim.dat', 'eef.dat', 'filters.dat', 'input.wav', ...
      'lpf.dat', 'omef.dat', 'outfile.dat'}
    if exist(name{1}, 'file') == 2
      delete(name{1});
    end
  end

  raw_fs = new_fs / 2;
  meta = struct( ...
    'ani_path', fullfile(workDir, 'nerve_image.ani'), ...
    'filter_freqs_path', fullfile(workDir, 'FilterFrequencies.txt'), ...
    'filter_freqs', filter_freqs, ...
    'raw_sample_freq', raw_fs, ...
    'downsample_factor', opts.DownsamplingFactor, ...
    'final_sample_freq', raw_fs / opts.DownsamplingFactor, ...
    'n_channels', opts.NumOfChannels, ...
    'trim_cols', round(n_zeros / 2), ...
    'n_zeros', n_zeros, ...
    'work_dir', workDir);
end

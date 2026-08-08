function state = leman_downsample_ani_init(nChannels, factor)
% Create streaming-downsample state without consuming samples.
%
% Discovers decimation phase and leading trim so filter+flush matches the
% local ``resample(..., 1, factor)`` (MATLAB and Octave differ here).

  if nargin < 2
    factor = 4;
  end
  if nChannels < 1
    error('leman_downsample_ani_init: nChannels must be >= 1');
  end
  if factor < 1 || factor ~= floor(factor)
    error('leman_downsample_ani_init: factor must be a positive integer');
  end

  [~, b] = resample(zeros(1, max(200, 10 * factor)), 1, factor);
  Lb = numel(b);
  [phase0, trim] = discover_resample_alignment(b, factor);
  state = struct( ...
    'n_channels', nChannels, ...
    'factor', factor, ...
    'b', b, ...
    'Lb', Lb, ...
    'zi', zeros(max(Lb - 1, 0), nChannels), ...
    'phase', phase0, ...
    'trim', trim, ...
    'skip_remaining', trim, ...
    'n_in', 0, ...
    'n_out', 0, ...
    'pending', zeros(nChannels, 0), ...
    'flushed', false, ...
    'finalised', false);
end

function [phase0, trim] = discover_resample_alignment(b, q)
% Match filter+decimate+trim against resample on a short probe vector.
  x = randn(1, max(512, 8 * q));
  y_ref = resample(x, 1, q);
  want = numel(y_ref);
  Lb = numel(b);
  yf = filter(b, 1, [x, zeros(1, max(Lb - 1, 0))]);

  best = inf;
  phase0 = 0;
  trim = 0;
  max_trim = min(200, max(0, numel(yf) - want));
  for off = 0:q - 1
    yd = yf(1 + off:q:end);
    for tr = 0:min(max_trim, max(0, numel(yd) - want))
      yt = yd(1 + tr:tr + want);
      d = max(abs(yt(:) - y_ref(:)));
      if d < best
        best = d;
        % Convert yf(1+off:q:end) subscript into the keep-when-phase==0
        % state machine's initial phase.
        phase0 = mod(-off, q);
        trim = tr;
      end
      if d < 1e-12
        return
      end
    end
  end
  if best > 1e-9
    error( ...
      ['leman_downsample_ani_init: could not match local resample ', ...
       '(best abs diff %.3e)'], best);
  end
end

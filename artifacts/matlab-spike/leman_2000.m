function leman_2000(in_file, out_file, local_decay_sec, global_decay_sec, detail)
% One-shot Leman (2000) analysis: set up the toolbox, analyse, write JSON.

  leman_2000_setup(fullfile(getenv('HOME'), 'matlab-compiler-spike', ...
                            'IPEMToolbox', 'IPEMToolbox'));
  res = leman_2000_compute(in_file, local_decay_sec, global_decay_sec, detail);
  leman_2000_write_json(res, out_file);
end

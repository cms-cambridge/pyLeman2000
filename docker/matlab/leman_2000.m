function leman_2000(in_file, out_file, local_decay_sec, global_decay_sec, detail)
% One-shot Leman (2000) analysis: set up the toolbox, analyse, write JSON.
%
% For source-mode runs set IPEM_TOOLBOX_DIR to the IPEMToolbox/IPEMToolbox
% directory (the folder that contains IPEMSetup.m). Deployed apps ignore that
% and locate the toolbox under ctfroot.

  leman_2000_setup(leman_2000_source_toolbox_dir());
  res = leman_2000_compute(in_file, local_decay_sec, global_decay_sec, detail);
  leman_2000_write_json(res, out_file);
end

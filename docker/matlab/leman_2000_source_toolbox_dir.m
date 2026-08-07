function toolbox_dir = leman_2000_source_toolbox_dir()
% Resolve the source-mode IPEM toolbox directory from the environment.
%
% Deployed apps never call this for pathing: leman_2000_setup searches
% under ctfroot when isdeployed. Source-mode runs must set IPEM_TOOLBOX_DIR
% to the IPEMToolbox/IPEMToolbox folder that contains IPEMSetup.m.

  toolbox_dir = getenv('IPEM_TOOLBOX_DIR');
  if isempty(toolbox_dir)
    error(['leman_2000_source_toolbox_dir: set IPEM_TOOLBOX_DIR to the ' ...
           'IPEMToolbox/IPEMToolbox directory that contains IPEMSetup.m']);
  end
end

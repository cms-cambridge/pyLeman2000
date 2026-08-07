function toolbox_dir = leman_2000_setup(source_toolbox_dir)
% Put the IPEM Toolbox on the path and initialise it, once per process.
%
% In a deployed (compiled) app the toolbox is extracted somewhere below
% ctfroot, so locate it by searching for IPEMSetup.m rather than hard-coding
% the layout, which depends on the app name and on how mcc -a packaged it.

  persistent initialised_dir
  if ~isempty(initialised_dir)
    toolbox_dir = initialised_dir;
    return
  end

  if isdeployed
    found = dir(fullfile(ctfroot, '**', 'IPEMSetup.m'));
    if isempty(found)
      error('leman_2000_setup: IPEMSetup.m not found below %s', ctfroot);
    end
    toolbox_dir = found(1).folder;
  else
    toolbox_dir = source_toolbox_dir;
  end

  addpath(toolbox_dir);
  octave_compat = fullfile(toolbox_dir, 'OctaveCompat');
  if exist(octave_compat, 'dir')
    addpath(octave_compat);
  end
  cd(toolbox_dir);
  IPEMSetup;

  initialised_dir = toolbox_dir;
end

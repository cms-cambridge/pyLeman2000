function package_matlab_worker()
% Create the custom Runtime image and package the compiled worker into Docker.
%
% Expected environment variables (set by scripts/build_matlab_image.sh):
%   PYLEMAN_BUILD_WORKER_DIR  - directory containing leman_2000_worker + buildresult.json
%   PYLEMAN_RUNTIME_IMAGE     - Docker tag for the custom Runtime image
%   PYLEMAN_WORKER_IMAGE      - Docker tag for the packaged worker image
%   PYLEMAN_DOCKER_CONTEXT    - output directory for generated Docker context

  worker_dir = require_env('PYLEMAN_BUILD_WORKER_DIR');
  runtime_image = require_env('PYLEMAN_RUNTIME_IMAGE');
  worker_image = require_env('PYLEMAN_WORKER_IMAGE');
  docker_context = require_env('PYLEMAN_DOCKER_CONTEXT');

  buildresult = fullfile(worker_dir, 'buildresult.json');
  if exist(buildresult, 'file') ~= 2
    error('package_matlab_worker: missing %s', buildresult);
  end

  if exist(docker_context, 'dir')
    rmdir(docker_context, 's');
  end
  mkdir(docker_context);

  runtime_context = fullfile(docker_context, 'runtime');
  mkdir(runtime_context);

  fprintf(1, 'Creating custom MATLAB Runtime image %s ...\n', runtime_image);
  compiler.runtime.createDockerImage(buildresult, ...
      'ImageName', runtime_image, ...
      'DockerContext', runtime_context, ...
      'OptionalDependencies', 'none', ...
      'VerbosityLevel', 'concise');

  app_context = fullfile(docker_context, 'worker');
  mkdir(app_context);

  fprintf(1, 'Packaging worker image %s ...\n', worker_image);
  compiler.package.docker( ...
      fullfile(worker_dir, 'leman_2000_worker'), ...
      buildresult, ...
      'ImageName', worker_image, ...
      'RuntimeImage', runtime_image, ...
      'DockerContext', app_context, ...
      'EntryPoint', 'leman_2000_worker', ...
      'ContainerUser', 'root', ...
      'VerbosityLevel', 'concise');

  fprintf(1, 'PACKAGE_MATLAB_WORKER_DONE\n');
end

function value = require_env(name)
  value = getenv(name);
  if isempty(value)
    error('package_matlab_worker: environment variable %s is not set', name);
  end
end

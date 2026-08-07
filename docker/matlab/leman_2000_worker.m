function leman_2000_worker(work_dir)
% Serve Leman (2000) requests from a queue directory, reusing one MATLAB process.
%
% Protocol (all paths must be absolute):
%   request   <work_dir>/req-<id>.json  with fields in_file, out_file,
%                                       local_decay_sec, global_decay_sec, detail
%   response  <work_dir>/res-<id>.json  with status "ok", or "error" and message
%   ready     <work_dir>/ready          written once the toolbox is initialised
%   shutdown  <work_dir>/stop           create this file to make the worker exit
%
% Requests must be published atomically (write under a temporary name, then
% rename) so the worker never reads a partially written file.
%
% For source-mode runs set IPEM_TOOLBOX_DIR to the IPEMToolbox/IPEMToolbox
% directory. Deployed apps locate the toolbox under ctfroot instead.

  work_dir = char(work_dir);
  leman_2000_setup(leman_2000_source_toolbox_dir());

  stop_file = fullfile(work_dir, 'stop');
  touch(fullfile(work_dir, 'ready'));
  fprintf(1, 'WORKER_READY\n');

  while ~exist(stop_file, 'file')
    pending = dir(fullfile(work_dir, 'req-*.json'));
    if isempty(pending)
      pause(0.005);
      continue
    end

    [~, order] = sort({pending.name});
    name = pending(order(1)).name;
    req_path = fullfile(work_dir, name);
    id = name(numel('req-') + 1:end - numel('.json'));

    try
      req = jsondecode(fileread(req_path));
      delete(req_path);
      res = leman_2000_compute(req.in_file, req.local_decay_sec, ...
                               req.global_decay_sec, req.detail);
      leman_2000_write_json(res, req.out_file);
      respond(work_dir, id, struct('status', 'ok'));
    catch err
      if exist(req_path, 'file')
        delete(req_path);
      end
      respond(work_dir, id, struct('status', 'error', 'message', err.message));
    end
  end
end

function respond(work_dir, id, payload)
  tmp_path = fullfile(work_dir, ['tmp-res-' id '.json']);
  leman_2000_write_json(payload, tmp_path);
  movefile(tmp_path, fullfile(work_dir, ['res-' id '.json']));
end

function touch(path)
  fid = fopen(path, 'w');
  if (fid >= 0)
    fclose(fid);
  end
end

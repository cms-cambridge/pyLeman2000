function leman_2000_write_json(res, out_file)
% Write a result struct to out_file as JSON.

  payload = jsonencode(res);
  fid = fopen(out_file, 'w');
  if (fid < 0)
    error('leman_2000_write_json: could not open output file %s', out_file);
  end
  fwrite(fid, payload);
  fclose(fid);
end

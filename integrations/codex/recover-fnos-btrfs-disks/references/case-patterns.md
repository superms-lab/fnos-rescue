# FNOS Btrfs case patterns

## Primary and secondary superblocks are blank

Inspect the third mirror at 256 GiB. Record FSID, generation, tree root, root level, system chunk
array, and device UUID. Never copy it back to the source; use a QCOW2 overlay.

## Chunk root reads as zeros

Use the system chunk array and a historical device tree to reconstruct persistent mappings. A
full `btrfs rescue chunk-recover` scan is slow, so save its results and reload them for every later
attempt. When device-tree leaves remain readable, prefer their verified extent mappings.

## A fast physical mapping pattern appears

Treat arithmetic patterns only as candidate generators. Require matching FSID, logical bytenr,
owner, generation, level, checksum, and byte-identical DUP copies before accepting a mapping.

## UFS names and sizes look correct but files do not open

Directory metadata survived while extent mappings or data did not. Validate content magic and
complete reads. Do not count placeholders or truncated files as recovered.

## Newer roots fail while older roots work

Prefer the newest coherent root that produces broad, validated content. Preserve results from
multiple generations because different historical roots may recover different files.

## Thousands of zero-byte files appear

Join extraction errors with the expected inventory. Keep placeholders until the failure manifest
distinguishes data-read failures from genuine empty files and metadata-only sidecars.

## The user wants to swap disks

Wait for all jobs, copy caches and logs, run `sync`, disconnect NBD, detach loop devices, stop the
recovery MD device, verify no holders remain, and then instruct the user to power down before
physical removal.

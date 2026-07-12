# Security policy

## Data safety

FNOS Rescue operates near irreplaceable data. Report safety issues privately before publishing
details when a bug could write to a source disk, confuse source and destination devices, expose
credentials, or corrupt recovery artifacts.

Open a private GitHub security advisory for this repository. Do not attach raw user disks,
credentials, private filenames, or unredacted logs.

## Supported versions

Only the latest tagged alpha release receives fixes during the `0.x` phase.

## Safety promise

Source-disk writes are considered critical vulnerabilities. The project will never silently
weaken read-only checks for convenience.

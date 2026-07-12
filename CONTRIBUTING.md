# Contributing

Contributions are welcome, especially generated corruption fixtures, reproducible device facts,
filesystem documentation, safety tests, and failure-manifest improvements.

## Rules

- Never commit real credentials, serial numbers, IP addresses, raw user disks, or private paths.
- Generate test images from scripts and document the exact corruption applied.
- Keep source devices read-only in every example.
- Put filesystem-specific logic behind a plugin boundary.
- Add a regression test for every safety fix.
- Do not call a file recovered until its full expected size and content format are validated.

## Development

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
python -m compileall -q src
```

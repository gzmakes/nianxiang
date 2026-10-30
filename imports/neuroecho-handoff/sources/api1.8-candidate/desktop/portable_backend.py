"""Read-only-bundle entry point; mutable data belongs to the selected app profile.

Invoked by the bundled interpreter with -I -B. No credential migration, automatic
model configuration, source connection or system permission request is performed.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys


def configure(project: Path, data_dir: Path):
    project = project.resolve(strict=True)
    data_dir = data_dir.absolute()
    if data_dir.is_symlink() or data_dir.resolve().is_relative_to(project):
        raise ValueError('Portable data must be outside the read-only application project.')
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if data_dir.resolve().is_relative_to(project):
        raise ValueError('Portable data directory resolves inside the application.')
    sys.dont_write_bytecode = True
    if (project / 'deps').is_dir():
        sys.path.insert(0, str(project / 'deps'))
    sys.path.insert(0, str(project))
    from server import core, model_settings
    core.DB_PATH = str(data_dir / 'data.db')
    model_settings.PATH = str(data_dir / 'model-settings.json')
    return core.DB_PATH, model_settings.PATH


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('port must be 1–65535')
    configure(Path(__file__).resolve().parent, args.data_dir)
    import uvicorn
    uvicorn.run('server.main:app', host='127.0.0.1', port=args.port)


if __name__ == '__main__':
    main()

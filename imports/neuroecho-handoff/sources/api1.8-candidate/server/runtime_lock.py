"""One server process per local database; released automatically on exit."""
import os
from pathlib import Path


class DatabaseLease:
    def __init__(self, database):
        self.path = Path(str(database) + '.server.lock')
        self.handle = None

    def __enter__(self):
        self.handle = os.fdopen(os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600), 'r+b')
        try:
            if os.name == 'nt':
                import msvcrt
                if self.path.stat().st_size == 0:
                    self.handle.write(b'0'); self.handle.flush()
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close(); self.handle = None
            raise RuntimeError('这份念响已在另一个窗口运行。请回到已打开的预览，或先停止那个窗口再启动。') from None
        return self

    def __exit__(self, *args):
        if self.handle is not None:
            self.handle.close(); self.handle = None

import pytest
from server.runtime_lock import DatabaseLease


def test_one_process_lease_per_database_and_automatic_release(tmp_path):
    path=tmp_path/'session.db'
    with DatabaseLease(path):
        with pytest.raises(RuntimeError, match='另一个窗口'):
            with DatabaseLease(path): pass
        with DatabaseLease(tmp_path/'different.db'): pass
    with DatabaseLease(path): pass

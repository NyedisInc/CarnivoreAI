
from contextlib import closing
from pathlib import Path

from src.core.crosstalk.fork.engine import _stamp_child
from src.core.db import connect, db_path_for, transaction
from src.core.db_migration import ensure_db_migrated


def test_fork_contact_identity_does_not_follow_reused_tmux_name(tmp_path: Path) -> None:
    ensure_db_migrated(tmp_path, 4, '0.8.2')
    with closing(connect(db_path_for(tmp_path))) as conn, transaction(conn):
        ids = []
        for identity, name, epoch in [('parent-uuid', 'parent', 1),
                                       ('child-uuid', 'child', 2), ('replacement-uuid', 'child', 3)]:
            row = conn.execute('''INSERT INTO sessions
                (session_uuid,tmux_socket,tmux_name,tmux_created_epoch,working_dir,origin,lifecycle,created_at,updated_at)
                VALUES (?,'test-fork',?,?,?,'created','running','x','x')''',
                (identity, name, epoch, str(tmp_path)))
            ids.append(row.lastrowid)
        parent_before = dict(conn.execute('SELECT * FROM sessions WHERE id=?', (ids[0],)).fetchone())
        assert _stamp_child(conn, row_id=ids[1], socket='test-fork', tmux_name='child',
                            epoch=3, parent_id=ids[0]) == (False, None)
        assert _stamp_child(conn, row_id=ids[1], socket='test-fork', tmux_name='child',
                            epoch=2, parent_id=ids[0]) == (True, 'child-uuid')
        assert conn.execute('SELECT parent_session_id FROM sessions WHERE id=?', (ids[2],)).fetchone()[0] is None
        assert dict(conn.execute('SELECT * FROM sessions WHERE id=?', (ids[0],)).fetchone()) == parent_before

        conn.execute("UPDATE sessions SET host_key='remote-test',tmux_created_epoch=2 WHERE id=?", (ids[2],))
        assert _stamp_child(conn, row_id=ids[2], socket='test-fork', tmux_name='child',
                            epoch=2, parent_id=ids[0]) == (False, None)
        assert conn.execute('SELECT parent_session_id FROM sessions WHERE id=?', (ids[2],)).fetchone()[0] is None

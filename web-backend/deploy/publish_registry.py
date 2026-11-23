import os
import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path


def publish_registry(source, destination):
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as staging:
        temporary = Path(staging.name)
    try:
        uri = source.resolve().as_uri() + "?mode=ro"
        with (
            closing(sqlite3.connect(uri, uri=True, timeout=2)) as original,
            closing(sqlite3.connect(temporary)) as snapshot,
            snapshot,
        ):
            snapshot.execute("CREATE TABLE peer (id TEXT PRIMARY KEY, pk BLOB, status INTEGER)")
            snapshot.executemany(
                "INSERT INTO peer VALUES (?, ?, ?)",
                original.execute(
                    "SELECT id, pk, status FROM peer "
                    "WHERE length(pk) = 32 AND (status IS NULL OR status = 1)"
                ),
            )
        shutil.chown(temporary, group="rustdesk-web")
        temporary.chmod(0o640)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    publish_registry(Path(sys.argv[1]), Path(sys.argv[2]))

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg

from shared.config import get_settings

SCHEMA_FILE = Path(__file__).resolve().parent.parent / "database" / "schema.sql"


def main() -> None:
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    with psycopg.connect(get_settings().database_url, prepare_threshold=None, autocommit=True) as conn:
        conn.execute(sql)
        tables = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name"
        ).fetchall()
    print("Schema applied. Tables:", ", ".join(t[0] for t in tables))


if __name__ == "__main__":
    main()

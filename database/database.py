from contextlib import contextmanager

from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool


class QueryResult:
    def __init__(self, cursor, on_close=None):
        self._cursor = cursor
        self._on_close = on_close
        self._closed = False

    def one(self):
        row = self._cursor.fetchone()
        self.close()
        return row

    def all(self):
        rows = self._cursor.fetchall()
        self.close()
        return rows

    def close(self):
        if self._closed:
            return
        self._cursor.close()
        if self._on_close:
            self._on_close()
        self._closed = True


class Database:
    def __init__(self, dsn: str, minconn: int = 1, maxconn: int = 10):
        self._pool = SimpleConnectionPool(minconn, maxconn, dsn)

    def execute_file(self, path: str):
        with open(path, "r", encoding="utf-8") as f:
            sql = f.read()

        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)

    def __call__(self, query: str, params: tuple = ()):
        conn = self._pool.getconn()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(query, params)
            conn.commit()
        except Exception:
            conn.rollback()
            cur.close()
            self._pool.putconn(conn)
            raise
        return QueryResult(cur, lambda: self._pool.putconn(conn))

    @contextmanager
    def transaction(self):
        conn = self._pool.getconn()

        def execute(query: str, params: tuple = ()):
            cur = conn.cursor(cursor_factory=RealDictCursor)
            try:
                cur.execute(query, params)
            except Exception:
                cur.close()
                raise
            return QueryResult(cur)

        try:
            yield execute
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)

    def close(self):
        self._pool.closeall()

from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool

class QueryResult:
    def __init__(self, cursor, conn, pool):
        self._cursor = cursor
        self._conn = conn
        self._pool = pool
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
        self._pool.putconn(self._conn)
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
        return QueryResult(cur, conn, self._pool)

    def close(self):
        self._pool.closeall()
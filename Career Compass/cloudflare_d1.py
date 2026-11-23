import sqlite3


class D1Row(dict):
    def __init__(self, values):
        super().__init__(values)
        self._values = tuple(values.values())

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


class D1Cursor:
    def __init__(self, rows=(), lastrowid=None, rowcount=-1):
        self._rows = list(rows)
        self._index = 0
        self.lastrowid = lastrowid
        self.rowcount = rowcount

    def fetchone(self):
        if self._index >= len(self._rows):
            return None
        row = self._rows[self._index]
        self._index += 1
        return row

    def fetchall(self):
        rows = self._rows[self._index :]
        self._index = len(self._rows)
        return rows

    def __iter__(self):
        return self

    def __next__(self):
        row = self.fetchone()
        if row is None:
            raise StopIteration
        return row


def _result_value(value, name, default=None):
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _as_row(row):
    if isinstance(row, dict):
        return D1Row(row)

    from js import Object

    keys = Object.keys(row).to_py()
    return D1Row({key: getattr(row, key) for key in keys})


def _translate_database_error(error):
    message = str(error)
    if any(
        marker in message.lower()
        for marker in ("constraint failed", "unique constraint", "primary key")
    ):
        raise sqlite3.IntegrityError(message) from error
    raise error


class D1Database:
    """Synchronous query facade over D1; each statement commits independently."""

    def __init__(self, binding, run_sync=None):
        self._binding = binding
        if run_sync is None:
            from pyodide.ffi import run_sync

        self._run_sync = run_sync

    def execute(self, sql, parameters=()):
        statement = sql.strip()
        if statement.upper() in ("BEGIN", "BEGIN IMMEDIATE", "COMMIT", "ROLLBACK"):
            raise RuntimeError(
                "D1 does not support SQL transaction statements; use a D1 batch."
            )

        try:
            prepared = self._binding.prepare(sql)
            if parameters:
                prepared = prepared.bind(*parameters)
            if statement[:6].upper() in ("SELECT", "PRAGMA") or statement[:4].upper() == "WITH":
                result = self._run_sync(prepared.all())
                rows = [_as_row(row) for row in _result_value(result, "results", ())]
                return D1Cursor(rows=rows, rowcount=len(rows))

            result = self._run_sync(prepared.run())
            metadata = _result_value(result, "meta", {})
            return D1Cursor(
                lastrowid=_result_value(metadata, "last_row_id"),
                rowcount=_result_value(metadata, "changes", -1),
            )
        except Exception as error:
            _translate_database_error(error)

    def executemany(self, sql, parameter_sets):
        try:
            statements = [
                self._binding.prepare(sql).bind(*parameters)
                for parameters in parameter_sets
            ]
            if not statements:
                return D1Cursor(rowcount=0)
            results = self._run_sync(self._binding.batch(statements))
            final_result = results[-1]
            metadata = _result_value(final_result, "meta", {})
            return D1Cursor(
                lastrowid=_result_value(metadata, "last_row_id"),
                rowcount=sum(
                    _result_value(_result_value(result, "meta", {}), "changes", 0)
                    for result in results
                ),
            )
        except Exception as error:
            _translate_database_error(error)

    def create_user(self, email, display_name, password_hash, created_at):
        try:
            self._run_sync(
                self._binding.batch(
                    [
                        self._binding.prepare(
                            """INSERT INTO users
                               (email, display_name, password_hash, theme, created_at)
                               VALUES (?, ?, ?, 'dark', ?)"""
                        ).bind(email, display_name, password_hash, created_at),
                        self._binding.prepare(
                            """INSERT INTO user_progress (user_id)
                               SELECT id FROM users WHERE email = ?"""
                        ).bind(email),
                    ]
                )
            )
            row = self.execute(
                "SELECT id FROM users WHERE email = ?", (email,)
            ).fetchone()
            if row is None:
                raise RuntimeError("The account was created but could not be loaded.")
            return row["id"]
        except Exception as error:
            _translate_database_error(error)

    def executescript(self, _sql):
        raise RuntimeError(
            "Apply Cloudflare D1 schema changes using the Wrangler migration command."
        )

    def commit(self):
        # D1 statements commit individually; multi-statement writes use batch().
        return None

    def rollback(self):
        return None

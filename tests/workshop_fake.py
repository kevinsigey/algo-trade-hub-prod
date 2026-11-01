"""An in-memory stand-in for the few supabase-py query calls the Workshop store makes."""


class Q:
    def __init__(self, db, table):
        self.db, self.table, self.filters, self.sort, self.row, self.patch = db, table, [], None, None, None

    def select(self, *_):
        return self

    def eq(self, col, val):
        self.filters.append((col, val))
        return self

    def is_(self, col, val):
        assert val == "null"
        self.filters.append((col, None))
        return self

    def order(self, col, desc=False):
        self.sort = (col, desc)
        return self

    def insert(self, row):
        self.row = row
        return self

    def update(self, patch):
        self.patch = patch
        return self

    def execute(self):
        rows = self.db.setdefault(self.table, [])
        if self.row is not None:
            new = []
            for r in self.row if isinstance(self.row, list) else [self.row]:
                row = {"id": len(rows) + 1, "created_at": f"2026-10-30T{len(rows) % 24:02d}:00:00Z", **r}
                rows.append(row)
                new.append(row)
            return type("R", (), {"data": new})()
        out = [r for r in rows if all(r.get(c) == v for c, v in self.filters)]
        if self.patch is not None:
            for r in out:
                r.update(self.patch)
        if self.sort:
            out.sort(key=lambda r: r[self.sort[0]], reverse=self.sort[1])
        return type("R", (), {"data": out})()


class DB:
    def __init__(self):
        self.db = {}

    def table(self, name):
        return Q(self.db, name)

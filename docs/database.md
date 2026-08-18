# Database

The schema lives in `backend/app/models/` as SQLAlchemy Core tables, and
migrations in `backend/migrations/`. The design and its rationale are in the
schema plan; this file is the runbook.

## Getting a Postgres

The schema needs **PostgreSQL 13 or newer** with two extensions:

| Extension  | Supplies                                             |
| ---------- | ---------------------------------------------------- |
| `pgcrypto` | `gen_random_uuid()`, the server-side default for ids |
| `vector`   | the `vector(384)` column type and HNSW index support |

The first migration creates both, so the role running it needs permission to
`CREATE EXTENSION` — on a managed host that usually means enabling them once in
the dashboard instead.

Any of these work:

- **Supabase** — Postgres with `vector` available; also provides auth, which is
  the other half of the multi-user work.
- **Neon** — plain Postgres, `vector` available.
- **Local** — install PostgreSQL, then build or install pgvector separately.
- **Docker** — `docker run -e POSTGRES_PASSWORD=dev -p 5432:5432 pgvector/pgvector:pg16`
  is the shortest path, since that image ships pgvector already.

## Configuring

Set `DATABASE_URL` in `backend/.env` (git-ignored):

```
DATABASE_URL=postgresql+psycopg://user:password@host:5432/jobtailor
```

The bare `postgres://` and `postgresql://` forms that hosting providers hand out
are accepted too — `migrations/env.py` rewrites them to the psycopg driver.

## Running migrations

From `backend/`:

```bash
python -m alembic upgrade head          # apply
python -m alembic downgrade -1          # undo the last revision
python -m alembic current               # what is applied
python -m alembic history               # what exists
```

**Review before applying.** Offline mode prints the exact statements without
touching a database, which is worth doing on anything shared:

```bash
python -m alembic upgrade head --sql
```

## Adding a migration

Edit the tables in `app/models/`, then:

```bash
python -m alembic revision --autogenerate -m "add whatever"
```

Autogenerate compares the metadata against a live database, so this needs
`DATABASE_URL` pointing at one that is already up to date. **Always read the
generated file** — autogenerate does not detect renames (it emits a drop plus
an add, which loses the data), and it cannot see changes to `CHECK` constraint
bodies or index expressions.

## Conventions

- **Primary keys** are UUIDv7 from `app.ids.uuid7()`. Time-ordered, so inserts
  append to the index rather than scattering across it, and `sorted(ids)` is
  creation order even within one millisecond.
- **Timestamps** are `timestamptz`, always UTC.
- **Enumerations** are `CHECK` constraints, not Postgres enum types — adding a
  value is a one-line alter rather than a migration dance.
- **Ownership** columns are denormalised for row-level security and kept
  consistent by composite foreign keys, not triggers. A child references its
  parent's `(id, user_id)` pair, so a row cannot end up under a parent its owner
  does not own. Any table used that way carries `UNIQUE (id, user_id)`.
- **`jsonb`** is only for genuinely schemaless values — template layouts,
  styles, event payloads. Anything relational is columns.

## Verification without a database

`python -m alembic upgrade head --sql` compiles the whole schema offline, and
the output can be checked against PostgreSQL's own grammar:

```python
import pglast
for statement in sql.split(";"):
    pglast.parse_sql(statement)
```

That catches syntax errors, but not whether the server accepts the semantics —
an unknown type, a missing extension, an immutability violation in an index
expression. Those need a real instance.

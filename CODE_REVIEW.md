# Code Review — Telegram Bot for Land Plot Management

## Summary

This is an async Telegram bot built with aiogram 3, SQLAlchemy 2, and PostgreSQL for managing land plot listings. The codebase is cleanly structured with separate layers for configuration, database, services, and bot handlers. However, there are several bugs, security concerns, and architectural issues that should be addressed.

---

## Critical / Bugs

### 1. `NameError` in login handler — `user` is undefined

**File:** `app/bot/handlers/auth.py:131`

```python
await _show_menu(message, state, plots_repo, user.is_admin)
```

The variable `user` is never assigned in `handle_login_password`. The return value of `auth_service.login()` is discarded. This will crash at runtime on every successful login.

**Fix:** Capture the return value:
```python
user = await auth_service.login(
    users_repo, username, message.text, message.from_user.id
)
```

### 2. Variables used outside `async for` session scope

Throughout the codebase, the pattern `async for session in get_session()` is used, but variables obtained from the session are then referenced **after** the `async for` block exits (and the session is closed). This is unreliable — the ORM objects may be in a detached/expired state.

**Affected locations:**
- `app/bot/handlers/plots.py:27` — `user` used after `async for` block
- `app/bot/handlers/plots.py:66-68` — `plot` used after session closes
- `app/bot/handlers/plots.py:58-61` — `places` used after session closes
- `app/bot/handlers/admin.py:31-32` — `user` used after session closes
- `app/bot/handlers/admin.py:37-40` — `places` used after session closes
- `app/bot/handlers/admin.py:196-197` — `plot` used after session closes

While `expire_on_commit=False` prevents expiration on commit, once the session is closed the objects become fully detached. Accessing lazy-loaded attributes would fail. For the current schema (no relationships), this works by accident, but it's fragile.

**Recommendation:** Move all logic that depends on queried data inside the `async for` block, or restructure to use `async with` instead.

### 3. `datetime.utcnow()` is deprecated

**File:** `app/db/repositories/users.py:63`

```python
user.last_login_at = datetime.utcnow()
```

`datetime.utcnow()` is deprecated since Python 3.12. It returns a naive datetime, while the column is `DateTime(timezone=True)`. This creates a mismatch — a naive UTC datetime stored in a timezone-aware column.

**Fix:** Use `datetime.now(datetime.timezone.utc)` instead.

---

## Security

### 4. Hardcoded database credentials in `docker-compose.yml`

**File:** `docker-compose.yml:8-9`

```yaml
POSTGRES_DB: bot
POSTGRES_USER: bot
POSTGRES_PASSWORD: bot
```

The database credentials are hardcoded with trivially guessable values. These should be externalized to environment variables or a `.env` file, consistent with how `bot` service uses `env_file: .env`.

### 5. No password deletion from Telegram message / FSM state

**Files:** `app/bot/handlers/auth.py:87,124`

Passwords are received as plain Telegram messages (`message.text`) and the raw text persists in:
- Telegram's message history (visible to the user in chat)
- aiogram's FSM state data (if `username` is stored, the password flow leaves it in memory)

Consider: (a) advising users to delete the password message, (b) attempting to delete it via `message.delete()`, and (c) calling `state.update_data(password=None)` after use.

### 6. Admin check relies solely on Telegram ID lookup

**File:** `app/bot/handlers/admin.py:28-32`

The `_ensure_admin` function queries the user by `telegram_id` on every admin action, which is correct. However, there's no rate limiting or logging of failed admin access attempts, which could be useful for auditing.

---

## Architecture / Design

### 7. `get_session()` as an async generator is misused

The `get_session()` function is an async generator (uses `yield`), intended for dependency injection frameworks. Throughout the handlers, it's consumed via `async for session in get_session()`, which works but is unconventional and misleading — it always yields exactly one session. A context manager (`@asynccontextmanager`) would be clearer:

```python
@asynccontextmanager
async def get_session():
    async with AsyncSessionFactory() as session:
        yield session
```

Then use `async with get_session() as session:` everywhere.

### 8. Module-level side effects in `app/db/session.py`

**File:** `app/db/session.py:7-10`

```python
settings = get_settings()
engine = create_async_engine(settings.database_url, echo=False)
```

The engine is created at import time. This means importing this module (even for tests) immediately requires `BOT_TOKEN` and `DATABASE_URL` environment variables to be set. This makes unit testing difficult and couples all imports to the environment.

### 9. Duplicated `PLOT_NUMBER_RE` regex

**Files:** `app/bot/handlers/plots.py:18` and `app/bot/handlers/admin.py:25`

The same regex `^[A-Za-z0-9_-]{1,20}$` is defined in two places. Should be a shared constant.

### 10. `_show_menu` is duplicated with different signatures

There are two `_show_menu` functions:
- `app/bot/handlers/auth.py:18` — takes `repo` and `is_admin` params
- `app/bot/handlers/admin.py:35` — creates its own session, hardcodes `is_admin=True`

This duplication leads to inconsistent behavior. The admin version always passes `is_admin=True`, while the auth version is parameterized. These should be consolidated.

### 11. No pagination beyond the initial 6 places

**File:** `app/db/repositories/plots.py:15`

```python
async def get_places_list(self, limit: int = 6) -> list[str]:
```

There is no offset/pagination support. If more than 6 places exist, users will never see them. The `limit=6` is hardcoded everywhere it's called.

---

## Dependencies / DevOps

### 12. Unpinned dependency versions in `requirements.txt`

```
aiogram==3.*
SQLAlchemy==2.*
asyncpg
alembic
pydantic-settings
passlib[argon2]
```

Only `aiogram` and `SQLAlchemy` have major version pins. `asyncpg`, `alembic`, `pydantic-settings`, and `passlib` are completely unpinned. This can lead to non-reproducible builds. Consider using a lockfile or pinning exact versions.

### 13. Migrations not run automatically

The `Dockerfile` runs `python main.py` directly. There is no migration step. If the database schema is not already up to date, the bot will fail. Consider adding an entrypoint script that runs `alembic upgrade head` before starting the bot, or adding a `depends_on` health check.

### 14. Deprecated Compose file version

**File:** `docker-compose.yml:1`

```yaml
version: "3.9"
```

The `version` key is obsolete in modern Docker Compose (v2+) and is ignored. It can be removed.

---

## Minor Issues

### 15. `from __future__ import with_statement` is unnecessary

**File:** `migrations/env.py:1`

This import has been a no-op since Python 2.6. It should be removed.

### 16. No `.gitignore` file

There is no `.gitignore` to exclude `__pycache__/`, `.env`, `*.pyc`, `.mypy_cache/`, etc. This risks committing secrets or build artifacts.

### 17. No `__init__.py` files visible

While Python 3 supports implicit namespace packages, explicit `__init__.py` files are conventional for application code and help tools (linters, type checkers) identify package boundaries.

### 18. `remember_login` field is unused

**File:** `app/db/models.py:56-58`

The `User.remember_login` column is defined and migrated but never read or written anywhere in the application code.

---

## Verdict

The project has a clean layer separation and sensible technology choices. The most urgent issues are the **`NameError` crash on login** (#1) and the **session scoping pattern** (#2). The security items (#4, #5) and dependency pinning (#12) should also be addressed before deploying to production.

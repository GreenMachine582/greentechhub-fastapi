[← Back to README](../README.md)

# 🧪 Testing

- `pytest` + `httpx`'s `ASGITransport` against a minimal reference FastAPI app wired with every `register_*` call — exercises the full [registration](registration.md) surface, not just unit-level function calls.
- Contract tests (from `greentechhub-core`) run against this package's concrete `IdentityProvider`/[health](health.md)/[query](query.md) implementations.
- GitHub Actions: lint + test, matching the rest of the ecosystem.

## Fixtures for a service's tests

`greentechhub_fastapi.testing` is a pytest plugin of HTTP fixtures (the `[testing]` extra). It builds on
greentechhub-core's database fixtures (`greentechhub_core.testing.sqlalchemy`, which it loads for you). Nothing
loads on install. A service opts in from its conftest and points the plugin at its app:

```python
# tests/conftest.py
pytest_plugins = ["greentechhub_fastapi.testing"]

@pytest.fixture(scope="session")
def gth_metadata():          # core's: the tables to create
    return SQLModel.metadata

@pytest.fixture
def gth_app():
    return app

@pytest.fixture
def gth_db():                # optional: the app's core Database
    return db

@pytest.fixture
def gth_create_user():       # for client_as
    async def create(user_id, password): ...
    return create
```

- `gth_client` is an `httpx.AsyncClient` on the app. The lifespan doesn't run, so there are no startup
  migrations. The app's `dependency_overrides` are restored after each test rather than cleared, so
  `register_auth`'s adapter survives.
- With `gth_db` set, every session the app opens (its `get_session`, its settings and grant stores, its
  readiness check) joins the test's rolled-back transaction.
- `await client_as("alice")` creates the user with `gth_create_user`, signs in through the web form and returns a
  client of its own. Call it again for another persona.
- `web_login(client, user_id, password)` and `post_login(...)` sign in the way a browser does: the `gth_csrf`
  token goes back with the form. The Secure session and CSRF cookies are re-set so they're sent over the test's
  `http://` URL. `hx_triggers(response)` parses the `HX-Trigger` header.

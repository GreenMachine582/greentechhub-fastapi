[← Back to README](../README.md)

# 🧪 Testing

- `pytest` + `httpx`'s `ASGITransport` against a minimal reference FastAPI app wired with every `register_*` call — exercises the full [registration](registration.md) surface, not just unit-level function calls.
- Contract tests (from `greentechhub-core`) run against this package's concrete `IdentityProvider`/[health](health.md)/[query](query.md) implementations.
- GitHub Actions: lint + test, matching the rest of the ecosystem.

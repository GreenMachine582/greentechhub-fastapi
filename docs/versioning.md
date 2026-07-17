[← Back to README](../README.md)

# 🏷️ Versioning & Distribution

- Own repo (`GreenMachine582/greentechhub-fastapi`), semver git tags, `pip`/`uv` git installs.
- Depends on a specific `greentechhub-core` version range — pin conservatively, since a breaking change in `greentechhub-core`'s `IdentityProvider` or `query` types breaks this package's contract with every FastAPI service in one step.
- **Non-breaking**: new `register_*` functions, new optional dependencies, new query params supported.
- **Breaking**: changing an existing `register_*` function's signature, changing the `Page`/`PageRequest` adapter's expected input shape.

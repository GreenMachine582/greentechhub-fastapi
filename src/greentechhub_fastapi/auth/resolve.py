"""resolve_dependency — call a Depends()-shaped async-generator dependency
outside of a route handler, respecting app.dependency_overrides.

FastAPI only substitutes app.dependency_overrides for parameters actually
injected via Depends() in a route's own signature. LoginViews.authenticate()
(views.py) is deliberately not one of those — it's a plain async method, not
a route parameter (see views.py's own "session/ORM-agnostic" design note) —
so a subclass calling its own `get_session`-style dependency directly always
gets the real implementation, never whatever override a test (or any other
runtime swap) installed on `app`. This isn't a LoginViews-specific problem:
any non-route code (a background task, a CLI command) that wants to reuse a
service's existing Depends()-shaped dependency hits the same gap.
resolve_dependency() closes it once, here, instead of every caller
reimplementing the aclosing()/anext() dance by hand.

Only handles the async-generator ("yield one value") shape most FastAPI
"give me a DB session" dependencies use — not a general Depends()-graph
resolver (that would mean reimplementing FastAPI's own dependency
resolution, exactly what calling outside a route is meant to avoid
needing). A dependency with its own nested Depends() sub-dependencies isn't
resolved here; the shape this targets is a plain, parameter-less generator
function, which is what a service's own get_session typically already is.
"""

from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import aclosing, asynccontextmanager

from fastapi import FastAPI


@asynccontextmanager
async def resolve_dependency[T](
    app: FastAPI, dependency: Callable[[], AsyncGenerator[T, None]]
) -> AsyncIterator[T]:
    """Yield whatever `dependency` (or its override on `app`, if any) yields.

    `dependency` must be a zero-argument async-generator function. Cleanup
    (whatever runs after `dependency`'s own `yield`, e.g. closing a session)
    is guaranteed via `aclosing` regardless of how the `async with` block
    using this exits — the same teardown guarantee FastAPI itself gives a
    `Depends()`-injected generator dependency after a request.
    """
    resolved = app.dependency_overrides.get(dependency, dependency)
    async with aclosing(resolved()) as generator:
        yield await anext(generator)

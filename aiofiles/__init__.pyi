from os import PathLike
from typing import Any, Protocol

class AsyncTextIO(Protocol):
    async def read(self, n: int = -1) -> str: ...
    async def write(self, s: str) -> int: ...


class AsyncOpenText(Protocol):
    async def __aenter__(self) -> AsyncTextIO: ...
    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> Any: ...


def open(
    file: str | PathLike[str],
    mode: str = ...,
    encoding: str | None = ...,
    *args: Any,
    **kwargs: Any,
) -> AsyncOpenText: ...

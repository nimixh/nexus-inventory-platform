"""File storage abstraction for connector file uploads.

LocalFileStorage is the default implementation. Swap to S3FileStorage later
by providing an implementation that satisfies the same protocol.
"""

import uuid
from pathlib import Path
from typing import Protocol

import anyio


class FileStorage(Protocol):
    """Protocol for pluggable file storage backends."""

    async def save(self, filename: str, content: bytes) -> str:
        """Save a file and return its storage path/key."""
        ...

    async def read(self, path: str) -> bytes:
        """Read a file by its storage path/key."""
        ...

    async def delete(self, path: str) -> None:
        """Remove a stored file."""
        ...


class LocalFileStorage:
    """Local filesystem implementation of FileStorage."""

    def __init__(self, base_dir: str = "./uploads") -> None:
        self.base_dir = Path(base_dir)

    async def save(self, filename: str, content: bytes) -> str:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"{uuid.uuid4().hex}_{filename}"
        path = self.base_dir / stored_name
        await anyio.Path(path).write_bytes(content)
        return str(path)

    async def read(self, path: str) -> bytes:
        return await anyio.Path(path).read_bytes()

    async def delete(self, path: str) -> None:
        await anyio.Path(path).unlink(missing_ok=True)

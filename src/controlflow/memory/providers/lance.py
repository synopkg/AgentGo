import functools
import uuid
from pathlib import Path
from typing import Callable, Dict, Optional

import lancedb
from lancedb.embeddings import get_registry
from lancedb.pydantic import LanceModel, Vector
from pydantic import Field, PrivateAttr

import controlflow
from controlflow.memory.memory import MemoryProvider


class LanceMemory(MemoryProvider):
    uri: Path = Field(
        default=controlflow.settings.home_path / "memory" / "lancedb",
        description="The URI of the Lance database to use.",
    )
    table_name: str = Field(
        "memory-{key}",
        description="""
            Optional; the name of the table to use. This should be a 
            string optionally formatted with the variable `key`, which 
            will be provCallablethe memory module. The default is `"memory-{{key}}"`.
            """,
    )
    embedding_fn: Callable = Field(
        default_factory=lambda: get_registry()
        .get("openai")
        .create(name="text-embedding-ada-002"),
        description="The LanceDB embedding function to use. Defaults to `get_registry().get('openai').create(name='text-embedding-ada-002')`.",
    )
    _cached_model: Optional[LanceModel] = None

    def get_model(self) -> LanceModel:
        if self._cached_model is None:
            fn = self.embedding_fn

            class Memory(LanceModel):
                id: str = Field(..., description="The ID of the memory.")
                text: str = fn.SourceField()
                vector: Vector(fn.ndims()) = fn.VectorField()  # noqa

            self._cached_model = Memory

        return self._cached_model

    def get_db(self) -> lancedb.DBConnection:
        return lancedb.connect(self.uri)

    def get_table(self, memory_key: str) -> lancedb.table.Table:
        table_name = self.table_name.format(key=memory_key)
        db = self.get_db()
        model = self.get_model()
        try:
            return db.open_table(table_name)
        except FileNotFoundError:
            return db.create_table(table_name, schema=model)

    def add(self, memory_key: str, content: str) -> str:
        memory_id = str(uuid.uuid4())
        table = self.get_table(memory_key)
        table.add([{"id": memory_id, "text": content}])
        return memory_id

    def delete(self, memory_key: str, memory_id: str) -> None:
        table = self.get_table(memory_key)
        table.delete(f'id = "{memory_id}"')

    def search(self, memory_key: str, query: str, n: int = 20) -> Dict[str, str]:
        table = self.get_table(memory_key)
        results = table.search(query).limit(n).to_pydantic(self.get_model())
        return {r.id: r.text for r in results}

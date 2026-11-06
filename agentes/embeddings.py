"""Modelos de embeddings para la memoria vectorial.

Alias (configurables en team.yaml -> settings.embedding_model):
  multilingue        paraphrase-multilingual-MiniLM-L12-v2 (fastembed, ~220 MB, ~50 idiomas)  [por defecto]
  multilingue-grande paraphrase-multilingual-mpnet-base-v2 (fastembed, ~1 GB, más preciso)
  ingles             all-MiniLM-L6-v2 por defecto de ChromaDB (~80 MB, entrenado en inglés)
También acepta cualquier nombre de modelo soportado por fastembed.
Los modelos se descargan una sola vez (caché local) y se cargan solo cuando se usan.
"""
from __future__ import annotations

import re

ALIASES = {
    "multilingue": ("fastembed", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"),
    "multilingue-grande": ("fastembed", "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"),
    "ingles": ("chroma", "all-MiniLM-L6-v2"),
}
DEFAULT_MODEL = "multilingue"


def resolve(name: str | None) -> tuple[str, str]:
    name = (name or DEFAULT_MODEL).strip()
    if name in ALIASES:
        return ALIASES[name]
    if name in ("default", "chroma"):
        return ALIASES["ingles"]
    return ("fastembed", name)


def collection_name(model: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", model.split("/")[-1]).strip("-_").lower()
    return f"mem-{slug}"[:63]


class FastEmbedEF:
    """Función de embeddings compatible con ChromaDB, basada en fastembed (ONNX, sin PyTorch)."""

    def __init__(self, model_name: str):
        self.model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from loguru import logger  # fastembed registra sus reintentos con loguru
                logger.disable("fastembed")
            except Exception:
                pass
            from fastembed import TextEmbedding  # type: ignore
            self._model = TextEmbedding(model_name=self.model_name)
        return self._model

    def __call__(self, input):  # noqa: A002 (firma exigida por ChromaDB)
        return [list(map(float, v)) for v in self._load().embed(list(input))]

    def embed_query(self, input):  # noqa: A002
        return self(input)

    @staticmethod
    def name() -> str:
        return "agentes-fastembed"

    def get_config(self) -> dict:
        return {"model_name": self.model_name}

    @staticmethod
    def build_from_config(config: dict) -> "FastEmbedEF":
        return FastEmbedEF(config["model_name"])

    def is_legacy(self) -> bool:
        return False

    def default_space(self) -> str:
        return "cosine"

    def supported_spaces(self) -> list[str]:
        return ["cosine", "l2", "ip"]


def make_ef(name: str | None):
    """Devuelve (funcion_embeddings | None, etiqueta_modelo). None = embeddings por defecto de ChromaDB."""
    backend, model = resolve(name)
    if backend == "chroma":
        return None, model
    try:
        import fastembed  # noqa: F401  # type: ignore
    except ImportError as e:
        raise RuntimeError(f"el modelo '{name}' requiere fastembed (reinstala con ./install.sh)") from e
    return FastEmbedEF(model), model

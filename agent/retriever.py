import hashlib
import os
from functools import lru_cache

from agent.semantic_layer import catalog, document
from model.database import ROOT

INDEX = ROOT / "chroma_store"


def embedding_model():
    return os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")


def collection_name():
    content = "\n".join([embedding_model(), *(document(t) for t in catalog())])
    return "olist_" + hashlib.sha256(content.encode()).hexdigest()[:20]


@lru_cache
def client(path):
    import chromadb
    from chromadb.config import Settings

    return chromadb.PersistentClient(path=str(path), settings=Settings(anonymized_telemetry=False))


def embeddings():
    from langchain_openai import OpenAIEmbeddings

    return OpenAIEmbeddings(model=embedding_model(), check_embedding_ctx_length=False,
                            request_timeout=30, max_retries=1)


def indexed_collection():
    if not (INDEX / "chroma.sqlite3").is_file():
        return None
    from chromadb.errors import NotFoundError

    try:
        collection = client(INDEX).get_collection(collection_name(), embedding_function=None)
    except NotFoundError:
        return None
    return collection if collection.count() == len(catalog()) else None


def retrieve(question):
    tables = catalog()
    collection = indexed_collection()
    if collection is None:
        return "full_schema", tables
    vector = embeddings().embed_query(question)
    matches = collection.query(query_embeddings=[vector], n_results=3, include=[])["ids"][0]
    names = list(dict.fromkeys([*matches, "fact_orders"]))
    by_name = {t["table_name"]: t for t in tables}
    return "chroma", [by_name[name] for name in names]

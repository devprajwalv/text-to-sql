import os

from agent import retriever
from agent.semantic_layer import catalog, document


def build():
    tables = catalog()
    docs = [document(table) for table in tables]
    vectors = retriever.embeddings().embed_documents(docs)
    collection = retriever.client(retriever.INDEX).get_or_create_collection(
        retriever.collection_name(), embedding_function=None,
        configuration={"hnsw": {"space": "cosine"}},
    )
    collection.upsert(ids=[t["table_name"] for t in tables], embeddings=vectors, documents=docs)
    return collection.count()


if __name__ == "__main__":
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("Set OPENAI_API_KEY in the root .env before building the schema index.")
    print(f"Indexed {build()} tables with {retriever.embedding_model()}.")

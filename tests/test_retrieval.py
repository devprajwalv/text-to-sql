from agent import retriever
from agent.build_index import build


class FixtureEmbeddings:
    def embed_documents(self, docs):
        return [[float(name in doc.splitlines()[0]) for name in ("fact_orders", "dim_users", "dim_reviews")]
                + [1.0] for doc in docs]

    def embed_query(self, question):
        return [1.0, 0.0, 0.0, 1.0]


def test_chroma_and_full_schema(tmp_path, monkeypatch):
    monkeypatch.setattr(retriever, "INDEX", tmp_path / "chroma")
    monkeypatch.setattr(retriever, "embeddings", FixtureEmbeddings)
    assert retriever.retrieve("orders")[0] == "full_schema"
    assert build() == build() == 6
    assert (retriever.INDEX / "chroma.sqlite3").is_file()
    mode, tables = retriever.retrieve("orders")
    assert mode == "chroma" and tables[0]["table_name"] == "fact_orders"
    monkeypatch.setenv("EMBEDDING_MODEL", "different-test-model")
    assert retriever.retrieve("orders")[0] == "full_schema"

"""Create the EULawIngestionStatus Weaviate collection.

This is the single source of truth for "what has been ingested" (per
docs/handoff/01_ARCHITECTURE.md "Why state tracking lives in Weaviate").
No vectors — metadata only.

Uniqueness: uuid5(celex + '::' + language). Ten fields total per
docs/handoff/03_SCHEMAS.md section 3.
"""

from __future__ import annotations

import os

import weaviate
from weaviate.classes.config import Configure, DataType, Property


COLLECTION_NAME = "EULawIngestionStatus"


def main() -> None:
    client = weaviate.connect_to_weaviate_cloud(
        cluster_url=os.environ["WEAVIATE_HOST"],
        auth_credentials=weaviate.auth.AuthApiKey(os.environ["WEAVIATE_API_KEY"]),
    )
    try:
        if client.collections.exists(COLLECTION_NAME):
            print(f"Collection {COLLECTION_NAME} already exists — no-op.")
            return

        client.collections.create(
            name=COLLECTION_NAME,
            vectorizer_config=Configure.Vectorizer.none(),
            properties=[
                Property(name="celex", data_type=DataType.TEXT),
                Property(name="language", data_type=DataType.TEXT),
                Property(name="document_type", data_type=DataType.TEXT),
                Property(name="cellar_recorded_at", data_type=DataType.DATE),
                Property(name="text_hash", data_type=DataType.TEXT),
                Property(name="status", data_type=DataType.TEXT),
                Property(name="last_updated_at", data_type=DataType.DATE),
                Property(name="superseded_by", data_type=DataType.TEXT),
                Property(name="retry_count", data_type=DataType.INT),
                Property(name="error_message", data_type=DataType.TEXT),
            ],
        )
        print(f"Created collection {COLLECTION_NAME}.")
    finally:
        client.close()


if __name__ == "__main__":
    main()

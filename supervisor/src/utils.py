from fastapi import status
from fastapi.exceptions import HTTPException

from shared.models import EmbeddingSource

REQUEST_TIMEOUT = 1e9


def form_scraper_request(request, embedding_source, channels):
    body = request.model_dump()
    body["channels"] = list(channels.json())

    match embedding_source:
        case EmbeddingSource.FTMLM:
            body["required_embedders"] = [
                "fast-text-embedder",
                "mini-lm-embedder",
            ]
        case EmbeddingSource.OPENAI:
            body["required_embedders"] = ["open-ai-embedder"]
        case EmbeddingSource.MLM:
            body["required_embedders"] = ["mini-lm-embedder"]

    return body


def form_linking_request(
    data, source: EmbeddingSource, linking_settings, method
):
    embeddings = None
    embs = data["embeddings"]
    match source:
        case EmbeddingSource.FTMLM:
            embeddings = [
                x + y
                for x, y in zip(
                    embs["mini-lm-embedder"],
                    embs["fast-text-embedder"],
                    strict=True,
                )
            ]
            config = linking_settings.ftmlm
        case EmbeddingSource.OPENAI:
            embeddings = embs["open-ai-embedder"]
            config = linking_settings.openai
        case EmbeddingSource.MLM:
            embeddings = embs["mini-lm-embedder"]
            config = linking_settings.mlm
        case _:
            possible_values = [e.value for e in EmbeddingSource]
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                f"Got unexpected embedding source, available one's: {possible_values}",
            )
    return {
        "text": data["text"],
        "date": data["date"],
        "source_id": data["source_id"],
        "channel_id": data["channel_id"],
        "method": method.value,
        "embeddings": embeddings,
        "config": (config.model_dump())[method.value],
    }

from fastapi import status
from fastapi.exceptions import HTTPException

from shared.models import EmbeddingSource

REQUEST_TIMEOUT = 1e9


def form_scraper_request(request, embedding_source, channels):
    body = request.model_dump()
    body["channels"] = channels

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
    match source:
        case EmbeddingSource.FTMLM:
            config = linking_settings.ftmlm
        case EmbeddingSource.OPENAI:
            config = linking_settings.openai
        case EmbeddingSource.MLM:
            config = linking_settings.mlm
        case _:
            possible_values = [e.value for e in EmbeddingSource]
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                f"Got unexpected embedding source, available ones: {possible_values}",
            )
    return {
        "entities": data,
        "config": (config.model_dump())[method.value],
        "embedding_source": source,
        "method": method.value,
    }


def chain_correlations(parent, children):
    return f"{parent} : {children}"

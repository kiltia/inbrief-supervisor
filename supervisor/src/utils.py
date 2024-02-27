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


def create_url(port, method, host="localhost"):
    return f"http://{host}:{port}{method}"

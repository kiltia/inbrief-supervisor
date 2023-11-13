from typing import List

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

from shared.models import JSONSettings


class NetworkSettings(BaseSettings):
    linker_port: int
    summarizer_port: int
    scraper_port: int
    editor_port: int
    linker_host: str
    summarizer_host: str
    scraper_host: str
    editor_host: str


class BM25Settings(BaseModel):
    depth: int
    threshold: float
    semantic_threshold: List[float]
    min_samples: int


class DBScanSettings(BaseModel):
    eps: float
    metric: str
    min_samples: int


class LinkerSettings(BaseModel):
    bm25: BM25Settings
    dbscan: DBScanSettings


class LinkingSettings(JSONSettings):
    openai: LinkerSettings
    ftmlm: LinkerSettings = Field(alias="ft+mlm")
    mlm: LinkerSettings

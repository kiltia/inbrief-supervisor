import json
from typing import List

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


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


class LinkingSettings(BaseModel):
    openai: LinkerSettings
    ftmlm: LinkerSettings = Field(alias="ft+mlm")
    mlm: LinkerSettings

    def __init__(self, path: str):
        with open(path, "r") as f:
            config_data = json.load(f)
            return super().__init__(**config_data)

    class Config:
        populate_by_name = True

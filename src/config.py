from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

from shared.models import DistancesMetric, JSONSettings, LinkingScorer


class NetworkSettings(BaseSettings):
    linker_port: int
    summarizer_port: int
    scraper_port: int
    editor_port: int
    linker_host: str
    summarizer_host: str
    scraper_host: str
    editor_host: str
    webapp_origin: str

    def __init__(self, _env_file: str):
        super().__init__(_env_file=_env_file)


class ClusteringConfig(BaseModel):
    params_range: dict
    immutable_config: dict = {}
    n_components: int


class ClusteringSettings(BaseModel):
    config: ClusteringConfig
    scorer: LinkingScorer
    metric: DistancesMetric


class LinkerSettings(BaseModel):
    kmeans: ClusteringSettings
    optics: ClusteringSettings
    agglomerative: ClusteringSettings
    hdbscan: ClusteringSettings
    spectral: ClusteringSettings


class LinkingSettings(JSONSettings):
    openai: LinkerSettings
    ftmlm: LinkerSettings = Field(alias="ft+mlm")
    mlm: LinkerSettings

    def __init__(self, path: str):
        super().__init__(path)

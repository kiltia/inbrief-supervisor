from enum import Enum
from typing import List

from pydantic import BaseModel
from utils import DEFAULT_END_DATE


class EmbeddingSource(Enum):
    FTMLM = "ft+mlm"
    OPENAI = "openai"
    MLM = "mlm"


class LinkingMethod(Enum):
    DBSCAN = "dbscan"
    BM25 = "bm25"
    NO_LINKER = "no_linker"


class SummaryMethod(Enum):
    OPENAI = "openai"
    BART = "bart"


class Density(Enum):
    SMALL = "small"
    AVERAGE = "average"
    LARGE = "large"


class SummaryType(Enum):
    STORYLINES = "storylines"
    SINGLE_NEWS = "single_news"


class Config(BaseModel):
    # NOTE(nrydanov): Isn't expected to give end-user possibility to choose
    # some of those parameters, but it's required for now
    embedding_source: EmbeddingSource
    linking_method: LinkingMethod
    summary_method: SummaryMethod
    required_density: List[Density]
    editor: str


class Payload(BaseModel):
    channels: List[str]
    # TODO(nrydanov): Change str for dates to datetime.time validation (#78)
    end_date: str = DEFAULT_END_DATE
    offset_date: str | None = None


class Request(BaseModel):
    config: Config
    payload: Payload

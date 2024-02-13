from ranking import Ranker, init_scorers

from config import LinkingSettings, NetworkSettings
from shared.db import Database, PgRepository, create_db_string
from shared.entities import (
    Callback,
    Config,
    Folder,
    Preset,
    Request,
    Story,
    StorySource,
    StorySources,
    Summary,
    User,
    UserPreset,
    UserPresets,
)
from shared.resources import SharedResources
from shared.utils import SHARED_CONFIG_PATH

network_settings = NetworkSettings(_env_file="config/network.cfg")
linking_settings = LinkingSettings("config/linker_config.json")


class Context:
    def __init__(self) -> None:
        self.shared_settings = SharedResources(
            f"{SHARED_CONFIG_PATH}/settings.json"
        )
        self.pg = Database(create_db_string(self.shared_settings.pg_creds))
        self.callback_repository = PgRepository(self.pg, Callback)
        self.preset_view = PgRepository(self.pg, UserPresets)
        self.user_repo = PgRepository(self.pg, User)
        self.preset_repo = PgRepository(self.pg, Preset)
        self.up_repo = PgRepository(self.pg, UserPreset)
        self.config_repo = PgRepository(self.pg, Config)
        self.summary_repo = PgRepository(self.pg, Summary)
        self.folder_repo = PgRepository(self.pg, Folder)
        self.ss_view = PgRepository(self.pg, StorySources)
        self.ss_repo = PgRepository(self.pg, StorySource)
        self.request_repo = PgRepository(self.pg, Request)
        self.story_repo = PgRepository(self.pg, Story)
        self.ranker = Ranker(init_scorers())

    async def init_db(self) -> None:
        await self.pg.connect()

    async def dispose_db(self) -> None:
        await self.pg.disconnect()


ctx = Context()

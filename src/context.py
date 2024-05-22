import asyncio
import logging
import os

from ranking import Ranker, init_scorers
from scheduler import Scheduler

from config import LinkingSettings, NetworkSettings
from redis.asyncio import Redis
from shared.db import Database, PgRepository, create_db_string
from shared.entities import (
    Callback,
    Config,
    Folder,
    Preset,
    Request,
    Schedule,
    ScheduledPreset,
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

logger = logging.getLogger("supervisor")


class Context:
    def __init__(self) -> None:
        self.shared_settings = SharedResources(
            f"{SHARED_CONFIG_PATH}/settings.json"
        )
        pg_pswd = os.getenv("POSTGRES_PASSWORD")
        pg_user = os.getenv("POSTGRES_USER")
        self.pg = Database(
            create_db_string(self.shared_settings.pg_creds, pg_pswd, pg_user)
        )
        self.redis = Redis(
            host=self.shared_settings.redis_config.host,
            port=self.shared_settings.redis_config.port,
            db=self.shared_settings.redis_config.db_num,
            password=os.getenv("REDIS_PASSWORD"),
            username=os.getenv("REDIS_USERNAME"),
        )
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
        self.schedule_repo = PgRepository(self.pg, Schedule)
        self.schedule_view = PgRepository(self.pg, ScheduledPreset)
        self.ranker = Ranker(init_scorers())
        self.scheduler = Scheduler(
            self.schedule_view,
            self.redis,
            timeout_sec=self.shared_settings.config.scheduler.timeout,
            interval_sec=self.shared_settings.config.scheduler.interval,
        )

    async def init_db(self) -> None:
        await self.pg.connect()

    async def dispose_db(self) -> None:
        await self.pg.disconnect()

    async def start_scheduler(self):
        loop = asyncio.get_event_loop()
        self.scheduler_task = loop.create_task(
            self.scheduler.job(), name="Scheduler Job"
        )
        logger.info("Created asyncronous scheduler job")

    async def stop_scheduler(self):
        self.scheduler_task.cancel()
        await self.scheduler_task
        await self.redis.aclose()


ctx = Context()

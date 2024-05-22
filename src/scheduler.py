import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Final

from croniter import croniter

from redis.asyncio import Redis
from shared.db import PgRepository
from shared.entities import ScheduledPreset

logger = logging.getLogger("supervisor")


class Scheduler:
    CHANNEL_NAME: Final[str] = "scheduled"

    def __init__(
        self,
        schedule_view: PgRepository,
        redis: Redis,
        timeout_sec: int,
        interval_sec: int,
    ):
        self.schedule_view = schedule_view
        self.redis = redis
        self.timeout_sec = timeout_sec
        self.interval_sec = interval_sec
        self.prev_run = None

    def _prepare_schedule_data(self, entry: ScheduledPreset) -> str:
        data = entry.model_dump()
        data["schedule_id"] = str(data["schedule_id"])
        data["preset_id"] = str(data["preset_id"])
        data["last_run"] = data["last_run"].isoformat()
        return json.dumps(data)

    async def job(self):
        logger.info("Starting scheduler job")
        while True:
            try:
                if (
                    self.prev_run is not None
                    and self.prev_run + timedelta(seconds=self.interval_sec)
                    > datetime.now()
                ):
                    await asyncio.sleep(self.timeout_sec)
                    continue

                [(_, sub_num)] = await self.redis.pubsub_numsub(
                    self.CHANNEL_NAME
                )
                if sub_num < 1:
                    logger.warn(
                        f'Seems like no one is subscribed to the Redis channel "{self.CHANNEL_NAME}". '
                        + "Scheduler will do nothing and skip an iteration."
                    )
                    await asyncio.sleep(self.timeout_sec)
                    continue

                logger.debug("Starting new scheduler job iteration")
                try:
                    records = await self.schedule_view.get()
                    logger.debug(
                        f"Pulled {len(records)} scheduling records from the database"
                    )
                    for entry in records:
                        # TODO(vinc3nzo): user's timezone handling
                        # See: https://github.com/kiltia/inbrief/issues/314
                        td = timedelta(hours=0)
                        tz = timezone(td)
                        if (
                            entry.active
                            and not entry.deleted
                            and croniter(entry.cron, entry.last_run).get_next(
                                datetime
                            )
                            <= datetime.now(tz)
                        ):
                            data = self._prepare_schedule_data(entry)
                            logger.debug(
                                f'Publishing scheduling entry to the Redis channel "{self.CHANNEL_NAME}"'
                            )
                            await self.redis.publish(self.CHANNEL_NAME, data)
                            logger.debug(
                                f'Successfully published scheduling entry to the Redis channel "{self.CHANNEL_NAME}"'
                            )
                            entry.last_run = datetime.now(tz)
                            await self.schedule_view.update(
                                entry, ["last_run"]
                            )
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"Unexpected error in scheduler:\n{e}")
                self.prev_run = datetime.now()
                logger.debug("Finished scheduler job iteration")
            except asyncio.CancelledError:
                logger.debug(
                    "Received cancel command in the scheduler, stopping"
                )
                break
        logger.info("Stopped scheduler job")

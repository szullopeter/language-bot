import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from database import Database
from config import Config

logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, db: Database):
        self.db = db
        self.scheduler = AsyncIOScheduler()

    def start(self, app):
        self.app = app

        # Daily vocab message — configurable time in config
        hour, minute = Config.DAILY_SEND_TIME.split(":")
        self.scheduler.add_job(
            self._send_daily_vocab,
            CronTrigger(hour=int(hour), minute=int(minute)),
            id="daily_vocab",
            replace_existing=True,
        )

        # Process queue every 5 minutes
        self.scheduler.add_job(
            self._process_queue,
            "interval",
            minutes=5,
            id="queue_processor",
            replace_existing=True,
        )

        self.scheduler.start()
        logger.info(f"Scheduler started. Daily vocab at {Config.DAILY_SEND_TIME} UTC.")

    async def _send_daily_vocab(self):
        from bot import format_vocab_message  # avoid circular import at module level
        logger.info("Running daily vocab job...")

        chat_ids = self.db.get_all_chat_ids()
        for chat_id in chat_ids:
            try:
                vocab = self.db.get_pending_vocab(chat_id)
                if not vocab:
                    continue

                message = "🌅 *Good morning! Here's your daily vocabulary:*\n\n"
                message += format_vocab_message(vocab)

                await self.app.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode="Markdown"
                )
                self.db.mark_vocab_sent(chat_id)
                logger.info(f"Sent {len(vocab)} vocab items to {chat_id}")
            except Exception as e:
                logger.error(f"Failed to send daily vocab to {chat_id}: {e}")

    async def _process_queue(self):
        from queue_worker import QueueWorker
        worker = QueueWorker(self.db)
        await worker.process_queue()

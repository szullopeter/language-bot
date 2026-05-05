import logging
import re
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from database import Database
from queue_worker import QueueWorker
from scheduler import Scheduler
from config import Config
from llm_client import LLMClient

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

db = Database()
llm = LLMClient()
worker = QueueWorker(db)
scheduler = Scheduler(db)

YOUTUBE_URL_PATTERN = re.compile(
    r"(?:https?://)?(?:[a-zA-Z0-9-]+\.)?(?:youtube\.com/(?:watch\?[\w\-&%=.]*v=[a-zA-Z0-9_-]+|playlist\?[\w\-&%=.]*list=[a-zA-Z0-9_-]+|v/[a-zA-Z0-9_-]+|embed/[a-zA-Z0-9_-]+|shorts/[a-zA-Z0-9_-]+)[\w\-&%=./]*|youtu\.be/[a-zA-Z0-9_-]+(?:\?[\w\-&%=.]+)?)"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to LangBot!\n\n"
        "Send me a YouTube video link to extract vocabulary, or just chat with me! "
        "I can also handle lyrics and multiple links at once.\n\n"
        "Commands:\n"
        "/vocab - Get today's new vocabulary\n"
        "/history - See vocabulary from past videos\n"
        "/setlang <lang> - Set target language\n"
        "/status - Check queue status"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id

    if not text:
        return

    # 1. Extract YouTube links
    full_urls = YOUTUBE_URL_PATTERN.findall(text)
    
    # 2. Handle links if any
    if full_urls:
        queued = 0
        for url in full_urls:
            # Basic normalization: ensure https
            if not url.startswith("http"):
                url = "https://" + url
            job_id = db.enqueue_video(chat_id, url)
            if job_id:
                queued += 1

        if queued:
            await update.message.reply_text(
                f"✅ Queued {queued} video(s) for processing.\n"
                "I'll extract new vocabulary shortly."
            )
            # Trigger background processing
            context.application.create_task(worker.process_queue())
        
        # 3. Check for remaining text (lyrics or questions)
        remaining_text = text
        for url in full_urls:
            remaining_text = remaining_text.replace(url, "")
        
        remaining_text = remaining_text.strip()
        # If there's significant text left, process it with LLM
        if len(remaining_text) < 2:
            return # Just links, we are done
        
        text_to_process = remaining_text
    else:
        text_to_process = text

    # 4. General chat via Groq with user context and compressed memory
    language = db.get_user_language(chat_id)
    known_words = list(db.get_known_words(chat_id))
    recent_vids = db.get_processed_videos(chat_id, limit=3)
    vid_titles = [v['title'] for v in recent_vids]
    
    # Get memory from DB
    chat_history, chat_summary = db.get_chat_memory(chat_id)
    
    response, new_history, new_summary = await llm.chat(
        text_to_process, 
        target_language=language, 
        known_words=known_words, 
        recent_videos=vid_titles,
        chat_history=chat_history,
        chat_summary=chat_summary
    )
    
    # Save updated memory
    db.save_chat_memory(chat_id, new_history, new_summary)
    
    # Ensure it's telegram compatible
    if len(response) > 3500:
        response = response[:3500].rstrip() + "... (shortened)"
    
    await update.message.reply_text(response)


async def vocab_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    # Check if a short ID was provided: /vocab ab12
    if context.args:
        short_id = context.args[0].lower()
        vocab = db.get_vocab_by_short_id(chat_id, short_id)
        if not vocab:
            await update.message.reply_text(f"No vocabulary found for ID: `{short_id}`", parse_mode="Markdown")
            return
        message = f"📚 *Vocabulary for video {short_id}*\n\n"
        message += format_vocab_message(vocab)
        await update.message.reply_text(message, parse_mode="Markdown")
        return

    vocab = db.get_pending_vocab(chat_id)

    if not vocab:
        await update.message.reply_text("No new vocabulary available yet. Queue some videos first!")
        return

    message = format_vocab_message(vocab)
    await update.message.reply_text(message, parse_mode="Markdown")
    # Mark these as sent so they don't show up in /vocab or the daily update again
    db.mark_vocab_sent(chat_id)
    await update.message.reply_text("✅ *Vocabulary marked as seen.* You won't see these in your next update.", parse_mode="Markdown")


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    videos = db.get_processed_videos(chat_id, limit=10)

    if not videos:
        await update.message.reply_text("No processed videos yet.")
        return

    lines = ["📚 *Recent Videos & Vocabulary*\n"]
    for v in videos:
        sid = v.get('short_id', '----')
        lines.append(f"• `{sid}`: [{v['title']}]({v['url']}) — {v['vocab_count']} words")

    lines.append("\n💡 Use `/vocab <id>` to see words for a specific video.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def setlang_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("Usage: /setlang French")
        return

    lang = " ".join(context.args).strip()
    db.set_user_language(chat_id, lang)
    await update.message.reply_text(f"✅ Target language set to: *{lang}*", parse_mode="Markdown")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    stats = db.get_queue_stats(chat_id)
    await update.message.reply_text(
        f"📊 *Queue Status*\n"
        f"Queued: {stats['queued']}\n"
        f"Processing: {stats['processing']}\n"
        f"Done: {stats['done']}\n"
        f"Failed: {stats['failed']}",
        parse_mode="Markdown"
    )


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    db.reset_user_state(chat_id)
    await update.message.reply_text("💥 *Everything has been reset.* Your history, vocabulary, and known words have been cleared.", parse_mode="Markdown")


def format_vocab_message(vocab: list) -> str:
    lines = ["📖 *New Vocabulary*\n"]
    for item in vocab:
        lines.append(f"*{item['word']}*")
        if item.get("phonetic"):
            lines.append(f"  _{item['phonetic']}_")
        lines.append(f"  🇬🇧 {item['definition_en']}")
        if item.get("definition_native"):
            lines.append(f"  🌍 {item['definition_native']}")
        if item.get("example"):
            lines.append(f"  💬 _{item['example']}_")
        lines.append("")
    return "\n".join(lines)


def main():
    app = Application.builder().token(Config.TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("vocab", vocab_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(CommandHandler("setlang", setlang_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    scheduler.start(app)

    logger.info("Bot started.")
    app.run_polling()


if __name__ == "__main__":
    main()

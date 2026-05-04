# LangBot 🎓

A Telegram bot that extracts new vocabulary from YouTube videos and delivers it to you daily.

## How it works

1. Send the bot a YouTube video or playlist link
2. It fetches the transcript (no download needed) using `youtube-transcript-api`
3. New words are filtered against your known vocabulary list
4. Each new word is looked up in a free dictionary API with English definitions + native language translation
5. Every morning (or on demand) you get a clean vocabulary message in Telegram

## Setup

### 1. Clone and configure
```bash
cp .env.example .env
# Edit .env and add your TELEGRAM_BOT_TOKEN
```

### 2. Run with Docker
```bash
docker compose up -d
```

### 3. Set your language
Send `/setlang French` (or German, Spanish, etc.) to the bot

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message |
| `/setlang <language>` | Set target language |
| `/vocab` | Get new vocabulary on demand |
| `/history` | See past processed videos |
| `/status` | Check queue status |

## Architecture

```
Telegram Bot (bot.py)
    │
    ├── Receives YouTube links → video_queue (SQLite)
    │
    ├── QueueWorker (queue_worker.py)
    │     ├── youtube-transcript-api → raw transcript
    │     ├── Token filter → removes known words + stop words
    │     └── DictionaryClient → definitions + translations
    │
    ├── Database (database.py)
    │     ├── video_queue     — job tracking
    │     ├── vocabulary      — extracted words per video
    │     └── known_words     — words user has already seen
    │
    └── Scheduler (scheduler.py)
          ├── Daily at 07:00 UTC → sends pending vocab via Telegram
          └── Every 5 minutes → processes queued videos
```

## Token efficiency

No LLM is used. The pipeline is:
- Local stop word filter (zero cost)
- Known words filter against SQLite (zero cost)  
- Free dictionary API (dictionaryapi.dev) for definitions
- Free MyMemory API for translations (1000 words/day free, more with API key)

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | required | Your bot token from @BotFather |
| `DAILY_SEND_TIME` | `07:00` | UTC time for daily vocab message |
| `MYMEMORY_API_KEY` | empty | Optional, increases translation rate limit |
| `DB_PATH` | `/data/langbot.db` | SQLite database path |

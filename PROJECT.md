# LangBot — Project Specification

> A Telegram bot that turns YouTube videos into daily vocabulary lessons. Zero cost, zero downloads, zero friction.

---

## Goal

Build a personal Telegram bot for immersion-based language learning. The user pastes YouTube links into Telegram. The bot fetches transcripts, filters out words the user already knows, looks up definitions and translations for free, and delivers a curated vocabulary digest every morning — timed so the user can review new words before watching the episode at breakfast.

Primary use case: learning French by watching content like Peppa Pig.

---

## Core User Flow

1. User sends a YouTube video or playlist URL to the Telegram bot
2. Bot validates the URL and adds it to the processing queue in SQLite
3. Background worker fetches the transcript via `youtube-transcript-api` (no audio/video download)
4. New words are extracted by filtering against a stop word list + the user's known vocabulary table
5. Each genuinely new word is looked up in a free dictionary API (definition, phonetic, example sentence)
6. Native-language translation of the definition fetched from MyMemory free API
7. At 07:00 UTC daily, APScheduler sends the vocab digest via Telegram
8. User can also request vocabulary on demand with `/vocab`

---

## Commands

| Command | Description |
|---|---|
| `/start` | Welcome message and instructions |
| `/setlang <language>` | Set target language (e.g. `/setlang French`) |
| `/vocab` | Get new vocabulary on demand |
| `/history` | List recently processed videos with word counts |
| `/status` | Show queue counts (queued / processing / done / failed) |

---

## System Design

```
Telegram Bot (bot.py)
    │
    ├── Receives YouTube links → SQLite: video_queue
    │
    ├── QueueWorker (queue_worker.py)
    │     ├── youtube-transcript-api → raw transcript text
    │     ├── Tokenizer + STOP_WORDS filter → candidate words
    │     ├── known_words DB filter → genuinely new words only
    │     └── DictionaryClient → definitions + translations
    │
    ├── Database (database.py) — SQLite
    │     ├── users          — chat_id, target language
    │     ├── video_queue    — job tracking per URL
    │     ├── vocabulary     — extracted words per video
    │     └── known_words    — all words the user has ever seen
    │
    └── Scheduler (scheduler.py) — APScheduler
          ├── Every 5 min  → process queued videos
          └── Daily 07:00  → send vocab digest via Telegram
```

### Components

**`bot.py`** — Entry point. Handles incoming Telegram messages and commands. Validates YouTube URLs with regex, enqueues them in SQLite, triggers the worker asynchronously.

**`queue_worker.py`** — Picks up queued videos and processes them end-to-end. Fetches transcript with language fallback. Tokenizes text into words (alpha, 3+ chars). Filters via STOP_WORDS (English + French common words built-in) and the known_words table. Caps at 100 new words per video.

**`dictionary.py`** — Async aiohttp client with a concurrency semaphore of 5. Uses `dictionaryapi.dev` for English definitions, phonetics, and example sentences (free, no key). Uses MyMemory for native-language translation of the definition (free, 1000 words/day, optional API key raises the limit). Words not found in the dictionary are silently skipped.

**`database.py`** — SQLite via stdlib. Single file at `/data/langbot.db` backed by a Docker volume. Context manager for connection safety with rollback. Known words are persisted permanently — the filter only improves over time.

**`scheduler.py`** — APScheduler `AsyncIOScheduler` running two jobs in-process: daily vocab sender and queue processor. No Redis or Celery needed.

### Data Model

| Table | Key Columns | Purpose |
|---|---|---|
| `users` | `chat_id`, `language` | Target language per user |
| `video_queue` | `id`, `chat_id`, `url`, `status`, `title`, `transcript` | Job tracking + transcript cache |
| `vocabulary` | `id`, `video_id`, `word`, `definition_en`, `definition_native`, `sent_at` | Per-video word store with delivery tracking |
| `known_words` | `chat_id`, `word` | Permanent filter — grows over time |

---

## Architectural Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Vocabulary extraction | Dictionary API + stop word filter | No LLM needed. Free, fast, deterministic. Filter improves naturally over time. |
| Transcript source | `youtube-transcript-api` | No audio download. Uses YouTube captions directly. |
| Database | SQLite | Zero ops, single file, sufficient for personal use. |
| Task scheduling | APScheduler in-process | No Redis or Celery. Single container, Python-native. |
| Translation | MyMemory free API | No API key required for basic use. 1000 words/day free. |
| Dictionary | `dictionaryapi.dev` | Fully free, no key, includes phonetics and example sentences. |
| LLM | **Groq (Llama-3)** | Used for conversational practice, grammar correction, and smart vocabulary extraction. |
| Language | Python 3.12 | Best ecosystem for Telegram bots and async. |
| Deployment | Docker + Compose | Single command, portable, volume-backed persistence. |

---

## Known Limitations

- **No captions = no transcript.** Videos without auto or manual captions are marked `failed` and skipped. In practice most major channels have auto-captions.
- **No morphological normalisation.** `run`, `ran`, `running` are treated as separate words. A stemmer would reduce noise.
- **MyMemory rate limit.** 1000 words/day on the free tier. A heavy day of queuing could hit this. Registering a free API key raises it to 10,000.
- **Playlist expansion (Experimental).** Basic support for enqueuing videos from a playlist link via scraping.
- **No retry backoff.** Failed jobs stay in `failed` state and require manual requeue.
- **Static stop word list.** Needs manual expansion for languages other than English and French.

---

## Upgrade Possibilities

### Short-term (low effort)
- Playlist URL expansion — auto-enqueue all videos from a playlist link
- Retry logic with exponential backoff for failed transcript fetches
- Lemmatization via NLTK or spaCy to collapse word forms
- `/forget <word>` command to remove a word from `known_words` and re-learn it
- `/recap <video>` command to show all vocabulary from a specific past video
- Configurable daily send time per user (not just global config)
- Word frequency weighting — surface the most frequent new words first

### Medium-term (moderate effort)
- Spaced repetition system (SRS) — resurface words on a forgetting curve (SM-2 algorithm)
- Inline Telegram quiz — bot quizzes you on yesterday's words before sending new ones
- Context sentences — store the exact transcript sentence where each word appeared
- Audio pronunciation — send a voice message with word pronunciation via gTTS
- `/stats` command — words learned per day/week/month
- Language auto-detection from transcript metadata

### Long-term (high effort)
- Optional LLM layer — use Claude or GPT only for ambiguous/complex words to generate richer explanations, keeping costs minimal and targeted
- Anki export — generate `.apkg` flashcard decks from learned vocabulary
- Notion / Obsidian sync — push new vocabulary to a personal knowledge base
- CEFR difficulty scoring — classify words by level (A1–C2) and filter by user's current level
- Multi-user hardening — rate limiting, per-user quotas, admin commands
- Web dashboard — read-only view of vocabulary history and progress

---

## Setup

```bash
cp .env.example .env
# Set TELEGRAM_BOT_TOKEN in .env
docker compose up -d
```

Then in Telegram:
```
/setlang French
https://www.youtube.com/watch?v=...
/vocab
```

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | required | From @BotFather |
| `DAILY_SEND_TIME` | `07:00` | UTC time for daily message |
| `MYMEMORY_API_KEY` | empty | Optional, raises translation rate limit |
| `DB_PATH` | `/data/langbot.db` | SQLite file path |

---

## File Structure

```
langbot/
├── bot.py            # Telegram bot, commands, message handler
├── queue_worker.py   # Transcript fetch, word extraction
├── dictionary.py     # dictionaryapi.dev + MyMemory client
├── database.py       # SQLite layer, all DB operations
├── scheduler.py      # APScheduler jobs
├── config.py         # Env var config
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

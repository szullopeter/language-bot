import asyncio
import logging
import re
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
from urllib.parse import urlparse, parse_qs
from dictionary import DictionaryClient
from database import Database
from llm_client import LLMClient

logger = logging.getLogger(__name__)

# Common words to always skip (extend as needed)
STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "to", "of", "in", "on", "at", "by", "for", "with", "about",
    "against", "between", "through", "during", "before", "after", "above",
    "below", "from", "up", "down", "out", "off", "over", "under", "again",
    "then", "once", "and", "but", "or", "nor", "so", "yet", "both",
    "either", "neither", "not", "no", "i", "me", "my", "we", "our",
    "you", "your", "he", "she", "it", "they", "them", "their", "this",
    "that", "these", "those", "what", "which", "who", "whom", "how",
    "when", "where", "why", "all", "each", "every", "both", "few", "more",
    "most", "other", "some", "such", "than", "too", "very", "just", "now",
    # French stop words
    "le", "la", "les", "un", "une", "des", "du", "de", "et", "en",
    "il", "elle", "ils", "elles", "je", "tu", "nous", "vous", "on",
    "ce", "se", "sa", "son", "ses", "mon", "ma", "mes", "ton", "ta",
    "tes", "qui", "que", "quoi", "dont", "où", "est", "sont", "été",
    "être", "avoir", "mais", "ou", "donc", "or", "ni", "car", "pour",
    "pas", "plus", "très", "bien", "tout", "même", "aussi",
}


class QueueWorker:
    def __init__(self, db: Database):
        self.db = db
        self.dictionary = DictionaryClient()
        self.llm = LLMClient()
        self._running = False

    async def process_queue(self):
        if self._running:
            return
        self._running = True
        try:
            videos = self.db.get_queued_videos(limit=5)
            for video in videos:
                await self._process_video(video)
        finally:
            self._running = False

    async def _process_video(self, video: dict):
        video_id = video["id"]
        url = video["url"]
        chat_id = video["chat_id"]
        language = video["language"]

        self.db.update_video_status(video_id, "processing")
        logger.info(f"Processing video: {url}")

        try:
            yt_id = self._extract_youtube_id(url)
            if not yt_id:
                raise ValueError(f"Could not extract YouTube ID from {url}")

            transcript_text, title = self._fetch_transcript(yt_id, language)
            self.db.update_video_status(video_id, "processing", title=title, transcript=transcript_text)

            known_words = self.db.get_known_words(chat_id)
            
            # Use LLM for "differentiating of new words"
            new_words = await self.llm.extract_interesting_words(transcript_text, language, known_words)
            
            if not new_words:
                logger.info("LLM extraction failed or returned nothing, falling back to manual extraction")
                new_words = self._extract_new_words(transcript_text, known_words)

            logger.info(f"Found {len(new_words)} new words for video {yt_id}")

            vocab = await self.dictionary.lookup_words(new_words, language)
            self.db.save_vocabulary(chat_id, video_id, vocab)
            self.db.update_video_status(video_id, "done", title=title)

        except (NoTranscriptFound, TranscriptsDisabled) as e:
            logger.warning(f"No transcript for {url}: {e}")
            self.db.update_video_status(video_id, "failed", error=str(e))
        except Exception as e:
            logger.error(f"Failed to process {url}: {e}")
            self.db.update_video_status(video_id, "failed", error=str(e))

    def _extract_youtube_id(self, url: str) -> str | None:
        parsed = urlparse(url)
        if parsed.hostname in ("youtu.be",):
            return parsed.path.lstrip("/").split("?")[0]
        if parsed.hostname in ("www.youtube.com", "youtube.com"):
            qs = parse_qs(parsed.query)
            return qs.get("v", [None])[0]
        return None

    def _fetch_transcript(self, yt_id: str, language: str) -> tuple[str, str]:
        lang_code = self._language_to_code(language)
        try:
            transcript = YouTubeTranscriptApi.get_transcript(yt_id, languages=[lang_code])
        except NoTranscriptFound:
            # Fallback: grab whatever's available
            transcript_list = YouTubeTranscriptApi.list_transcripts(yt_id)
            transcript = transcript_list.find_transcript([lang_code]).fetch()

        full_text = " ".join(entry["text"] for entry in transcript)
        # Title isn't in the transcript API, so we derive it from the ID
        title = f"YouTube Video ({yt_id})"
        return full_text, title

    def _extract_new_words(self, text: str, known_words: set) -> list[str]:
        # Tokenize: lowercase alpha words only
        words = re.findall(r"\b[a-zA-ZÀ-ÿ]{3,}\b", text.lower())
        # Deduplicate and filter
        seen = set()
        new_words = []
        for word in words:
            if word in seen:
                continue
            seen.add(word)
            if word in STOP_WORDS:
                continue
            if word in known_words:
                continue
            new_words.append(word)
        return new_words[:100]  # Cap at 100 per video to avoid overload

    def _language_to_code(self, language: str) -> str:
        mapping = {
            "french": "fr", "german": "de", "spanish": "es",
            "italian": "it", "portuguese": "pt", "dutch": "nl",
            "japanese": "ja", "chinese": "zh", "korean": "ko",
            "russian": "ru", "arabic": "ar", "polish": "pl",
        }
        return mapping.get(language.lower(), "fr")

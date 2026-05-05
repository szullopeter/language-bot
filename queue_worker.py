import asyncio
import logging
import re
import json
import http.cookiejar
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
from youtube_transcript_api.proxies import GenericProxyConfig
from requests import Session
from urllib.parse import urlparse, parse_qs
from dictionary import DictionaryClient
from database import Database
from llm_client import LLMClient
from config import Config

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

            # Handle Playlists (Experimental)
            if yt_id.startswith("playlist:"):
                playlist_id = yt_id.split(":")[1]
                logger.info(f"Expanding playlist: {playlist_id}")
                video_ids = self._expand_playlist(playlist_id)
                if not video_ids:
                    raise ValueError(f"Could not find any videos in playlist {playlist_id} (YouTube may be blocking scraping)")
                
                logger.info(f"Found {len(video_ids)} videos in playlist. Enqueuing them...")
                for vid in video_ids:
                    new_url = f"https://www.youtube.com/watch?v={vid}"
                    self.db.enqueue_video(chat_id, new_url)
                
                self.db.update_video_status(video_id, "done", title=f"Playlist: {playlist_id} ({len(video_ids)} videos)")
                # Trigger queue processing again for the new items
                asyncio.create_task(self.process_queue())
                return

            transcript_text, title = self._fetch_transcript(yt_id, language)
            self.db.update_video_status(video_id, "processing", title=title, transcript=transcript_text)

            known_words = self.db.get_known_words(chat_id)
            
            new_words = []
            if Config.USE_LLM_EXTRACTION:
                # Use LLM for "differentiating of new words"
                new_words = await self.llm.extract_interesting_words(transcript_text, language, known_words)
            
            if not new_words:
                if Config.USE_LLM_EXTRACTION:
                    logger.info("LLM extraction failed or returned nothing, falling back to manual extraction")
                else:
                    logger.info("Using manual word extraction (LLM disabled)")
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
        hostname = parsed.hostname
        if not hostname:
            return None
            
        if hostname in ("youtu.be",):
            return parsed.path.lstrip("/").split("?")[0]
            
        if "youtube.com" in hostname:
            qs = parse_qs(parsed.query)
            # Prioritize video ID
            if "v" in qs:
                return qs["v"][0]
            # Handle /shorts/ID or /v/ID or /embed/ID
            path_parts = parsed.path.split("/")
            if len(path_parts) >= 3 and path_parts[1] in ("shorts", "v", "embed"):
                return path_parts[2]
            # Handle playlist ID as fallback if no video ID
            if "list" in qs:
                return f"playlist:{qs['list'][0]}"
                
        return None

    def _expand_playlist(self, playlist_id: str) -> list[str]:
        """Simple scraping to get video IDs from a playlist page."""
        try:
            # Setup proxies
            proxies_dict = None
            if Config.YOUTUBE_PROXIES:
                try:
                    proxies_dict = json.loads(Config.YOUTUBE_PROXIES)
                except Exception as e:
                    logger.error(f"Failed to parse YOUTUBE_PROXIES: {e}")

            # Setup cookies via custom Session
            session = Session()
            if Config.YOUTUBE_COOKIES:
                try:
                    import http.cookiejar
                    cj = http.cookiejar.MozillaCookieJar(Config.YOUTUBE_COOKIES)
                    cj.load(ignore_discard=True, ignore_expires=True)
                    session.cookies = cj
                except Exception as e:
                    logger.error(f"Failed to load YOUTUBE_COOKIES: {e}")

            url = f"https://www.youtube.com/playlist?list={playlist_id}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            }
            response = session.get(url, headers=headers, timeout=10, proxies=proxies_dict)
            if response.status_code != 200:
                return []
            
            # Try multiple patterns
            video_ids = re.findall(r'"videoId":"([^"]+)"', response.text)
            if not video_ids:
                # Fallback: look for v=ID in links
                video_ids = re.findall(r'v=([a-zA-Z0-9_-]{11})', response.text)
            
            # Remove duplicates and preserve order
            seen = set()
            unique_ids = []
            for vid in video_ids:
                if vid not in seen:
                    seen.add(vid)
                    unique_ids.append(vid)
            return unique_ids
        except Exception as e:
            logger.error(f"Failed to expand playlist {playlist_id}: {e}")
            return []

    def _fetch_transcript(self, yt_id: str, language: str) -> tuple[str, str]:
        lang_code = self._language_to_code(language)
        
        # Setup proxies
        proxy_config = None
        proxies_dict = None
        if Config.YOUTUBE_PROXIES:
            try:
                proxies_dict = json.loads(Config.YOUTUBE_PROXIES)
                proxy_config = GenericProxyConfig(
                    http_url=proxies_dict.get("http"),
                    https_url=proxies_dict.get("https")
                )
            except Exception as e:
                logger.error(f"Failed to parse YOUTUBE_PROXIES: {e}")

        # Setup cookies via custom Session
        session = Session()
        if Config.YOUTUBE_COOKIES:
            try:
                cj = http.cookiejar.MozillaCookieJar(Config.YOUTUBE_COOKIES)
                cj.load(ignore_discard=True, ignore_expires=True)
                session.cookies = cj
                logger.info(f"Loaded YouTube cookies from {Config.YOUTUBE_COOKIES}")
            except Exception as e:
                logger.error(f"Failed to load YOUTUBE_COOKIES: {e}")

        # 1. Try to fetch the real YouTube title
        title = f"YouTube Video ({yt_id})"
        try:
            url = f"https://www.youtube.com/watch?v={yt_id}"
            # Use the same session and proxies for title fetching
            response = session.get(url, timeout=5, proxies=proxies_dict)
            if response.status_code == 200:
                match = re.search(r"<title>(.*?) - YouTube</title>", response.text)
                if match:
                    title = match.group(1)
        except Exception as e:
            logger.debug(f"Failed to fetch real title for {yt_id}: {e}")

        try:
            # 2. Try to get the preferred language (manual or generated)
            api = YouTubeTranscriptApi(proxy_config=proxy_config, http_client=session)
            transcript_list = api.list(yt_id)
            try:
                # find_transcript prefers manual, then falls back to generated for the given codes
                transcript = transcript_list.find_transcript([lang_code]).fetch().to_raw_data()
            except NoTranscriptFound:
                # 3. Fallback: Get the first available transcript in any language
                logger.info(f"No {lang_code} transcript found for {yt_id}, falling back to first available.")
                transcript = next(iter(transcript_list)).fetch().to_raw_data()

        except Exception as e:
            logger.error(f"Failed to fetch any transcript for {yt_id}: {e}")
            raise

        full_text = " ".join(entry["text"] for entry in transcript)
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

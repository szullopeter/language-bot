import asyncio
import logging
import aiohttp
from config import Config

logger = logging.getLogger(__name__)

FREE_DICT_API = "https://api.dictionaryapi.dev/api/v2/entries"


class DictionaryClient:
    """
    Uses the free dictionaryapi.dev for English definitions.
    For non-English target languages, we use MyMemory free translation API
    to get the definition_native field without needing paid API keys.
    """

    async def lookup_words(self, words: list[str], target_language: str) -> list[dict]:
        results = []
        async with aiohttp.ClientSession() as session:
            # Batch with concurrency limit to be respectful
            semaphore = asyncio.Semaphore(5)
            tasks = [
                self._lookup_word(session, semaphore, word, target_language)
                for word in words
            ]
            entries = await asyncio.gather(*tasks, return_exceptions=True)

        for entry in entries:
            if isinstance(entry, dict) and entry.get("word"):
                results.append(entry)

        return results

    async def _lookup_word(
        self,
        session: aiohttp.ClientSession,
        semaphore: asyncio.Semaphore,
        word: str,
        target_language: str
    ) -> dict | None:
        async with semaphore:
            try:
                # Try English definition first
                definition_en, phonetic, example = await self._fetch_en_definition(session, word)

                # If no English definition found, skip this word
                if not definition_en:
                    return None

                # Get native language translation
                definition_native = None
                if target_language.lower() != "english":
                    definition_native = await self._translate(session, definition_en, target_language)

                return {
                    "word": word,
                    "phonetic": phonetic,
                    "definition_en": definition_en,
                    "definition_native": definition_native,
                    "example": example,
                }
            except Exception as e:
                logger.debug(f"Failed to look up '{word}': {e}")
                return None

    async def _fetch_en_definition(
        self, session: aiohttp.ClientSession, word: str
    ) -> tuple[str | None, str | None, str | None]:
        url = f"{FREE_DICT_API}/en/{word}"
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    return None, None, None
                data = await resp.json()
                if not data:
                    return None, None, None

                entry = data[0]
                phonetic = entry.get("phonetic")

                meanings = entry.get("meanings", [])
                definition_en = None
                example = None

                for meaning in meanings:
                    defs = meaning.get("definitions", [])
                    if defs:
                        definition_en = defs[0].get("definition")
                        example = defs[0].get("example")
                        if definition_en:
                            break

                return definition_en, phonetic, example
        except Exception:
            return None, None, None

    async def _translate(
        self, session: aiohttp.ClientSession, text: str, target_language: str
    ) -> str | None:
        """
        Uses MyMemory free translation API — no API key needed for basic usage.
        Rate limit: 1000 words/day free. For higher volume, add MYMEMORY_API_KEY.
        """
        lang_code = self._language_to_code(target_language)
        url = "https://api.mymemory.translated.net/get"
        params = {
            "q": text[:500],  # Truncate long definitions
            "langpair": f"en|{lang_code}",
        }
        if Config.MYMEMORY_API_KEY:
            params["key"] = Config.MYMEMORY_API_KEY

        try:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                translated = data.get("responseData", {}).get("translatedText")
                return translated if translated else None
        except Exception:
            return None

    def _language_to_code(self, language: str) -> str:
        mapping = {
            "french": "fr", "german": "de", "spanish": "es",
            "italian": "it", "portuguese": "pt", "dutch": "nl",
            "japanese": "ja", "chinese": "zh", "korean": "ko",
            "russian": "ru", "arabic": "ar", "polish": "pl",
        }
        return mapping.get(language.lower(), "fr")

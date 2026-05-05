import asyncio
import logging
import aiohttp
from llm_client import LLMClient

logger = logging.getLogger(__name__)

class DictionaryClient:
    """
    Uses LLM (Groq) for high-quality, context-aware definitions and translations.
    This avoids errors when looking up non-English words in an English dictionary.
    """

    def __init__(self):
        self.llm = LLMClient()

    async def lookup_words(self, words: list[str], target_language: str) -> list[dict]:
        results = []
        # Batch with concurrency limit
        semaphore = asyncio.Semaphore(5)
        tasks = [
            self._lookup_word(semaphore, word, target_language)
            for word in words
        ]
        entries = await asyncio.gather(*tasks, return_exceptions=True)

        for entry in entries:
            if isinstance(entry, dict) and entry.get("word"):
                results.append(entry)

        return results

    async def _lookup_word(
        self,
        semaphore: asyncio.Semaphore,
        word: str,
        target_language: str
    ) -> dict | None:
        async with semaphore:
            try:
                # Use LLM for everything to ensure context-aware results
                details = await self.llm.define_word(word, target_language)
                
                if not details or not details.get("definition_en"):
                    return None

                return {
                    "word": word,
                    "phonetic": details.get("phonetic"),
                    "definition_en": details.get("definition_en"),
                    "definition_native": details.get("definition_native"),
                    "example": details.get("example"),
                }
            except Exception as e:
                logger.debug(f"Failed to look up '{word}': {e}")
                return None

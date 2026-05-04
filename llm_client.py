import logging
from groq import Groq
from config import Config

logger = logging.getLogger(__name__)

class LLMClient:
    def __init__(self):
        self.client = Groq(api_key=Config.GROQ_API_KEY) if Config.GROQ_API_KEY else None
        self.model = Config.GROQ_MODEL

    async def chat(self, text: str, system_prompt: str = None) -> str:
        if not self.client:
            return "Groq API key not configured."

        if not system_prompt:
            system_prompt = (
                "You are a Telegram chatbot and you respond short and clear, "
                "always in just a few sentences, like in a messaging app. "
                "Do NOT use complex markdown or long lists. "
                "If you use bold or italics, ensure they are correctly closed. "
                "Keep the answer concise and suitable for a mobile screen."
            )

        try:
            # Groq's python client is synchronous for chat.completions.create, 
            # but we can wrap it or use it as is if we don't mind the block, 
            # or use async if they have an async client.
            # Actually groq has AsyncGroq.
            from groq import AsyncGroq
            async_client = AsyncGroq(api_key=Config.GROQ_API_KEY)
            
            completion = await async_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                model=self.model,
                temperature=0.7,
                max_tokens=1024,
            )
            return completion.choices[0].message.content
        except Exception as e:
            logger.error(f"Groq chat error: {e}")
            return "I had problems processing your message, sorry."

    async def extract_interesting_words(self, transcript: str, language: str, known_words: set) -> list[str]:
        if not self.client:
            return []

        # We don't want to send the whole transcript if it's too long.
        # But for Peppa Pig (10 min), it's probably fine.
        # Let's truncate to first 2000 words.
        context_transcript = " ".join(transcript.split()[:2000])
        
        known_words_str = ", ".join(list(known_words)[:100]) # Limit known words to avoid token bloat
        
        prompt = (
            f"Transcript ({language}):\n{context_transcript}\n\n"
            f"User already knows these words: {known_words_str}\n\n"
            f"Identify the top 15 most interesting or important vocabulary words from this transcript "
            f"that are suitable for a language learner and are NOT in the 'already knows' list. "
            f"Return ONLY a comma-separated list of words, nothing else."
        )

        try:
            from groq import AsyncGroq
            async_client = AsyncGroq(api_key=Config.GROQ_API_KEY)
            
            completion = await async_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": f"You are a linguistic expert helping a {language} learner."},
                    {"role": "user", "content": prompt},
                ],
                model=self.model,
                temperature=0.3,
            )
            response = completion.choices[0].message.content
            words = [w.strip().lower() for w in response.split(",") if w.strip()]
            return words
        except Exception as e:
            logger.error(f"Groq extraction error: {e}")
            return []

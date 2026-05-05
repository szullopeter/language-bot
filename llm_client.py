import logging
from groq import AsyncGroq
from config import Config

logger = logging.getLogger(__name__)

class LLMClient:
    def __init__(self):
        self.api_key = Config.GROQ_API_KEY
        self.model = Config.GROQ_MODEL
        self.client = AsyncGroq(api_key=self.api_key) if self.api_key else None

    async def chat(self, text: str, target_language: str = "French", known_words: list = None, recent_videos: list = None, chat_history: list = None, chat_summary: str = "") -> tuple[str, list, str]:
        if not self.client:
            return "Groq API key not configured.", [], ""

        known_words_str = ", ".join(known_words[:20]) if known_words else "None yet"
        videos_str = ", ".join(recent_videos[:3]) if recent_videos else "None recently"
        
        system_prompt = (
            f"You are LangBot, a helpful and friendly language learning assistant on Telegram. "
            f"The user is currently learning {target_language}. "
            f"Recent videos they've watched: {videos_str}. "
            f"Some words they have recently learned or added to their list: {known_words_str}. "
            "Your goal is to help them practice this language, explain grammar, or just chat about the videos they've seen.\n\n"
            "CRITICAL RESPONSE FORMAT:\n"
            "1. Every response MUST start with a corrected version of the user's last message for grammar and typos inside square brackets [ ]. "
            "If the user's message was already perfect, repeat it exactly inside the brackets.\n"
            "2. Follow the brackets with exactly two line breaks (\\n\\n).\n"
            "3. Then provide your actual response.\n\n"
            "CONDITIONAL LYRICS TRANSLATION:\n"
            "If and ONLY IF the user provides a long text (like song lyrics, a poem, or a long paragraph with multiple lines), "
            "you must translate it line-by-line. Format: Original Line \\n [English Translation Line]. "
            "If the message is short or a normal question/sentence, DO NOT use the line-by-line format; just respond normally.\n\n"
            "CONVERSATION & MEMORY:\n"
            "Maintain a friendly, messaging-app style. "
            "You have access to a summary of the past conversation to stay relevant. "
            "Keep answers concise to save tokens and screen space."
        )

        if chat_summary:
            system_prompt += f"\n\nContext of previous conversation: {chat_summary}"

        messages = [{"role": "system", "content": system_prompt}]
        
        # Add recent history
        if chat_history:
            messages.extend(chat_history)
        
        # Add current user message
        messages.append({"role": "user", "content": text})

        try:
            completion = await self.client.chat.completions.create(
                messages=messages,
                model=self.model,
                temperature=0.7,
                max_tokens=1024,
            )
            response = completion.choices[0].message.content
            
            # Post-processing to enforce the format: [Correction]\n\nResponse
            if "[" in response and "]" in response:
                # Ensure it starts with "["
                start_idx = response.find("[")
                # Extract the part starting from "["
                response = response[start_idx:]
                
                # Ensure exactly two newlines after the closing bracket "]"
                end_bracket_idx = response.find("]")
                correction = response[:end_bracket_idx + 1]
                actual_response = response[end_bracket_idx + 1:].strip()
                
                if actual_response:
                    response = f"{correction}\n\n{actual_response}"
                else:
                    response = correction # Case where there's no response after correction (unlikely)
            
            # Update history: add user message and assistant response
            new_history = (chat_history or []) + [
                {"role": "user", "content": text},
                {"role": "assistant", "content": response}
            ]
            
            # Compression logic: if history > 10 messages, summarize and truncate
            new_summary = chat_summary
            if len(new_history) > 10:
                logger.info("Compressing chat history...")
                new_summary = await self.summarize_history(new_summary, new_history[:6])
                new_history = new_history[6:]
            
            return response, new_history, new_summary
            
        except Exception as e:
            logger.error(f"Groq chat error: {e}")
            return "I had problems processing your message, sorry.", [], ""

    async def summarize_history(self, old_summary: str, messages_to_summarize: list) -> str:
        try:
            history_text = "\n".join([f"{m['role']}: {m['content']}" for m in messages_to_summarize])
            prompt = (
                f"Existing summary: {old_summary}\n\n"
                f"New messages:\n{history_text}\n\n"
                f"Create a single, highly compressed paragraph summarizing the key points and context of the conversation so far. "
                f"Focus on the user's progress, topics discussed, and any specific language learning goals mentioned."
            )
            
            completion = await self.client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "You are a memory module. Summarize conversations concisely."},
                    {"role": "user", "content": prompt},
                ],
                model=self.model,
                temperature=0.3,
                max_tokens=256,
            )
            return completion.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Summarization error: {e}")
            return old_summary

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
            completion = await self.client.chat.completions.create(
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

    async def define_word(self, word: str, language: str) -> dict:
        if not self.client:
            return {}

        prompt = (
            f"Word: {word}\n"
            f"Language: {language}\n\n"
            f"Provide the following details for this word in the context of the {language} language:\n"
            f"1. A concise English translation/definition.\n"
            f"2. A concise definition in {language}.\n"
            f"3. A phonetic pronunciation (IPA).\n"
            f"4. A short example sentence in {language} followed by its English translation in parentheses.\n\n"
            f"Return the result as a JSON object with keys: 'definition_en', 'definition_native', 'phonetic', 'example'. "
            f"The 'example' value must be a single string (e.g., 'Sentence in {language} (English translation)')."
        )

        try:
            completion = await self.client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "You are a helpful linguistic assistant. Return ONLY valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                model=self.model,
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            import json
            data = json.loads(completion.choices[0].message.content)
            
            # Safeguard: if LLM returns example as a dict, flatten it
            example = data.get("example")
            if isinstance(example, dict):
                native = example.get("sentence_native") or example.get("native") or ""
                en = example.get("sentence_en") or example.get("en") or ""
                data["example"] = f"{native} ({en})".strip() if native and en else (native or en)
            
            return data
        except Exception as e:
            logger.error(f"Groq definition error for {word}: {e}")
            return {}

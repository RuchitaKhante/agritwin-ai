"""
Thin wrapper around the Groq API. Every other file calls ask_llm()
instead of touching the Groq client directly.
"""

from groq import Groq
from chatbot.config import GROQ_API_KEY, LLM_MODEL


class LLMUnavailableError(RuntimeError):
    """Raised when the Groq model cannot be reached / is not configured. The API turns it into HTTP 503."""


_client = None


def _get_client():
    """Create the Groq client lazily so a missing key gives a clear error instead of crashing at import."""
    global _client
    if _client is None:
        if not GROQ_API_KEY:
            raise LLMUnavailableError("GROQ_API_KEY is not set. Add it to the .env file and restart the server.")
        _client = Groq(api_key=GROQ_API_KEY)
    return _client


def ask_llm(prompt: str) -> str:
    """
    Send a prompt to the Groq LLM and return the text response.
    Retries once if the response looks cut off, is empty, or the call fails.
    Raises LLMUnavailableError if every attempt fails (no fake answer is returned).
    """
    last_text = ""
    last_error = None

    for attempt in range(2):  # try up to 2 times
        try:
            kwargs = dict(
                model=LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                # gpt-oss is a reasoning model: hidden "thinking" tokens count against max_tokens, so a small
                # limit used to produce empty / cut-off answers. Keep reasoning short, leave room for the answer.
                max_tokens=1500,
                reasoning_effort="low",
            )
            try:
                response = _get_client().chat.completions.create(**kwargs)
            except TypeError:
                # older groq SDK without the reasoning_effort argument
                kwargs.pop("reasoning_effort", None)
                response = _get_client().chat.completions.create(**kwargs)
            choice = response.choices[0]
            text = (choice.message.content or "").strip()
            last_text = text

            looks_cut_off = choice.finish_reason == "length"
            is_empty = len(text) == 0

            if (looks_cut_off or is_empty) and attempt == 0:
                print(f"[llm_client] Response {'looked cut off' if looks_cut_off else 'was empty'}, retrying once...")
                continue

            if is_empty:
                last_error = "the model returned an empty answer"
                break

            return text

        except LLMUnavailableError:
            raise
        except Exception as e:
            last_error = str(e)
            print(f"[llm_client] Groq API error (attempt {attempt + 1}): {e}")

    if last_text:
        return last_text

    raise LLMUnavailableError(f"The language model did not answer ({last_error or 'unknown error'}).")
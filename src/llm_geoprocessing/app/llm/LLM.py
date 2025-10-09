# LLM.py
"""
Tiny, opinionated OOP wrapper to talk to LLMs via APIs.
- Base class `LLM` defines a stable interface.
- `ChatGPT` uses the OpenAI API.
- `Gemini` uses the Google Gemini API.

Design goals:
- Simple, readable, and easy to extend.
- Minimal magic; explicit over clever.
- Short, surgical comments only.
"""

from __future__ import annotations

import os
import sys
import time
import io
import contextlib
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Sequence, Union, List, Tuple, Callable


# ----- Ensure UTF-8 stdin/stdout/stderr in Python 3.7+ ----------------------------
# This prevents crashes from UnicodeDecodeError or UnicodeEncodeError
# For example, it allows using accented characters and emojis in input() and print().

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ---- Types -----------------------------------------------------------------

Message = Dict[str, str]  # {"role": "user" | "system" | "assistant", "content": "..."}


# ---- Exceptions -------------------------------------------------------------

class LLMError(Exception):
    """Base error for this module."""
    pass


class LLMConfigError(LLMError):
    """Raised when the client is not properly configured."""
    pass


# ---- Helpers: robust stderr silencer (fd-level) ----------------------------

class _SilenceStderrFD:
    """
    Context manager that silences OS-level stderr (fd=2) for the whole process.
    Works even when native libs write directly to fd 2.

    If fd-level redirection fails (e.g., no fileno), it degrades gracefully.
    """
    def __init__(self) -> None:
        self._stderr_fd: Optional[int] = None
        self._saved_fd: Optional[int] = None
        self._enabled: bool = False

    def __enter__(self):
        try:
            # Get the actual file descriptor for current stderr
            self._stderr_fd = sys.stderr.fileno()
            # Duplicate it so we can restore later
            self._saved_fd = os.dup(self._stderr_fd)
            # Point fd 2 to /dev/null
            with open(os.devnull, "wb") as devnull:
                os.dup2(devnull.fileno(), self._stderr_fd)
            self._enabled = True
        except Exception:
            # If anything fails, we just do nothing.
            self._enabled = False
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if self._enabled and self._stderr_fd is not None and self._saved_fd is not None:
                os.dup2(self._saved_fd, self._stderr_fd)  # restore original fd 2
                os.close(self._saved_fd)
        finally:
            self._stderr_fd = None
            self._saved_fd = None
            self._enabled = False
        # don't suppress exceptions
        return False


def _quiet_ctx(enabled: bool):
    """
    Combined quiet context:
      1) fd-level silencer (handles native libs)
      2) Python-level redirect_stderr (handles Python loggers)
    Order matters: FD first, then Python redirect.
    """
    if not enabled:
        return contextlib.nullcontext()

    stack = contextlib.ExitStack()
    # Enter fd-level first
    stack.enter_context(_SilenceStderrFD())
    # Then Python-level
    stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
    return stack


# ---- Base class ------------------------------------------------------------

class LLM(ABC):
    def __init__(
        self,
        model: Optional[str] = None,
        *,
        temperature: float = 0.3,
        timeout: float = 60.0,
        max_retries: int = 2,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self._configured = False

    def config_api(self, **_: Any) -> None:
        raise NotImplementedError

    def config_local(self, **_: Any) -> None:
        self._configured = True

    @abstractmethod
    def send_msg(
        self,
        messages: Union[str, Message, Sequence[Message]],
        *,
        temperature: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> str:
        raise NotImplementedError

    # ---- Utilities (shared) -------------------------------------------------
    def _require_configured(self) -> None:
        if not self._configured:
            raise LLMConfigError("Client not configured. Call `.config_api(...)` first.")

    @staticmethod
    def _normalize_messages(
        messages: Union[str, Message, Sequence[Message]],
    ) -> List[Message]:
        if isinstance(messages, str):
            return [{"role": "user", "content": messages}]
        if isinstance(messages, dict):
            role = messages.get("role")
            content = messages.get("content")
            if role not in {"user", "assistant", "system"} or not isinstance(content, str):
                raise LLMError("Invalid message dict; expected {'role','content'}.")
            return [messages]  # type: ignore
        if not isinstance(messages, Sequence):
            raise LLMError("messages must be str, dict, or sequence of dicts.")
        out: List[Message] = []
        for m in messages:
            if not isinstance(m, dict):
                raise LLMError("Each message must be a dict with 'role' and 'content'.")
            role = m.get("role")
            content = m.get("content")
            if role not in {"user", "assistant", "system"} or not isinstance(content, str):
                raise LLMError("Invalid message entry.")
            out.append({"role": role, "content": content})
        return out

    def _with_retry(self, fn: Callable[[], str]) -> str:
        attempts = self.max_retries + 1
        last_exc: Optional[BaseException] = None
        for i in range(attempts):
            try:
                return fn()
            except KeyboardInterrupt:
                raise
            except BaseException as e:
                last_exc = e
                if i >= attempts - 1:
                    break
                time.sleep(min(2 ** i, 8) + 0.05 * i)
        raise LLMError(f"LLM call failed after {attempts} attempt(s): {last_exc}")


# ---- OpenAI: ChatGPT --------------------------------------------

class ChatGPT(LLM):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._openai_client = None

    def config_api(
        self,
        *,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        timeout: Optional[float] = None,
    ) -> None:
        api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise LLMConfigError("Missing OPENAI_API_KEY.")
        try:
            from openai import OpenAI  # type: ignore
        except Exception as e:
            raise LLMConfigError("openai SDK not installed. `pip install openai`") from e

        self._openai_client = OpenAI(api_key=api_key)
        if model:
            self.model = model
        if temperature is not None:
            self.temperature = float(temperature)
        if timeout is not None:
            self.timeout = float(timeout)
        if not self.model:
            self.model = "gpt-4o-mini"
        self._configured = True

    def send_msg(
        self,
        messages: Union[str, Message, Sequence[Message]],
        *,
        temperature: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> str:
        self._require_configured()
        assert self._openai_client is not None

        msgs = self._normalize_messages(messages)
        chat_messages = [{"role": m["role"], "content": m["content"]} for m in msgs]
        curr_temp = self.temperature if temperature is None else float(temperature)

        def _call() -> str:
            resp = self._openai_client.chat.completions.create(
                model=self.model,
                messages=chat_messages,
                temperature=curr_temp,
                max_tokens=max_output_tokens,
                timeout=self.timeout,
                **kwargs,
            )
            return (resp.choices[0].message.content or "").strip()

        return self._with_retry(_call)


# ---- Google: Gemini --------------------------------------------------------

class Gemini(LLM):
    """
    Gemini client using `google-generativeai`.

    Env:
      - GEMINI_API_KEY or GOOGLE_API_KEY

    Use quiet=True to suppress native gRPC/absl stderr chatter on init.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.quiet: bool = bool(kwargs.pop("quiet", False))
        super().__init__(*args, **kwargs)
        self._genai = None
        self._base_model = None
        self._model_name_cache: Optional[str] = None

    def config_api(
        self,
        *,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        timeout: Optional[float] = None,
        grpc_verbosity: Optional[str] = None,
        glog_minloglevel: Optional[str] = None,
    ) -> None:
        # Optional: adjust env-based logging BEFORE importing SDKs.
        if grpc_verbosity:
            os.environ["GRPC_VERBOSITY"] = grpc_verbosity  # e.g., "ERROR"
        if glog_minloglevel:
            os.environ["GLOG_minloglevel"] = glog_minloglevel  # e.g., "3"

        api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise LLMConfigError("Missing GEMINI_API_KEY (or GOOGLE_API_KEY).")

        # Silence native stderr during import/configure too (logs can appear here).
        with _quiet_ctx(self.quiet):
            try:
                import google.generativeai as genai  # type: ignore
            except Exception as e:
                raise LLMConfigError(
                    "google-generativeai not installed. `pip install google-generativeai`"
                ) from e

            genai.configure(api_key=api_key)
            self._genai = genai

            if model:
                self.model = model
            if temperature is not None:
                self.temperature = float(temperature)
            if timeout is not None:
                self.timeout = float(timeout)
            if not self.model:
                self.model = "gemini-1.5-flash"

            self._base_model = genai.GenerativeModel(self.model)
            self._model_name_cache = self.model
            self._configured = True

    @staticmethod
    def _to_gemini_contents(messages: List[Message]) -> Tuple[Optional[str], List[Dict[str, Any]]]:
        system_parts: List[str] = []
        contents: List[Dict[str, Any]] = []
        for m in messages:
            role, text = m["role"], m["content"]
            if role == "system":
                system_parts.append(text)
            elif role == "assistant":
                contents.append({"role": "model", "parts": [text]})
            else:  # user
                contents.append({"role": "user", "parts": [text]})
        system_instr = "\n".join(p.strip() for p in system_parts if p.strip()) or None
        return system_instr, contents

    def send_msg(
        self,
        messages: Union[str, Message, Sequence[Message]],
        *,
        temperature: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
        quiet: Optional[bool] = None,
        **kwargs: Any,
    ) -> str:
        self._require_configured()
        assert self._genai is not None and self._base_model is not None

        msgs = self._normalize_messages(messages)
        system_instr, contents = self._to_gemini_contents(msgs)
        curr_temp = self.temperature if temperature is None else float(temperature)

        generation_config: Dict[str, Any] = {"temperature": curr_temp}
        if max_output_tokens is not None:
            generation_config["max_output_tokens"] = int(max_output_tokens)

        model_name = self._model_name_cache or self.model
        if system_instr:
            model = self._genai.GenerativeModel(model_name, system_instruction=system_instr)
        else:
            model = self._base_model

        use_quiet = self.quiet if quiet is None else bool(quiet)

        def _call() -> str:
            with _quiet_ctx(use_quiet):
                resp = model.generate_content(
                    contents=contents,
                    generation_config=generation_config,
                    request_options={"timeout": self.timeout},
                    **kwargs,
                )
            return (getattr(resp, "text", None) or "").strip()

        return self._with_retry(_call)


# ---- Smoke test / CLI ------------------------------------------------------

if __name__ == "__main__":
    # Example Gemini interactive loop
    try:
        g = Gemini(model="gemini-2.5-flash", quiet=True)
        g.config_api()  # reads GEMINI_API_KEY / GOOGLE_API_KEY
        # Clear console
        os.system("cls" if os.name == "nt" else "clear")
        while True:
            msg = input("You: ")
            if msg.strip().lower() in {"exit", "quit"}:
                break
            print("Gemini:", g.send_msg(msg))
    except Exception as e:
        print("[Gemini error]", e)

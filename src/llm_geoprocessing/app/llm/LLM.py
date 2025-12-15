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
import json
import contextlib
import urllib.request
import urllib.error
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Sequence, Union, List, Tuple, Callable

from llm_geoprocessing.app.logging_config import get_logger
logger = get_logger("geollm")


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


# ---- Chat memory -----------------------------------------------------

class ChatMemory:
    """
    Tiny, explicit chat memory.

    - Store messages as [{'role','content'}, ...]
    - Add/insert/edit/delete easily.
    - Render history to a single human-readable string using universal role labels.

    Example string:
      User: Hi, my name is Cristhian
      Assistant: Hi Cristhian, my name is Gemini
      User:
    """
    def __init__(self, *, user_name: str = "User") -> None:
        self.user_name = user_name
        self._messages: List[Message] = []

    # ---- basic ops ----
    def add(self, role: str, content: str) -> None:
        if role not in {"user", "assistant", "system"}:
            raise LLMError("Invalid role; expected 'user', 'assistant', or 'system'.")
        if not isinstance(content, str):
            raise LLMError(f"Content must be a string. Got {type(content)}.Content: {content}")
        self._messages.append({"role": role, "content": content})

    def add_user(self, content: str) -> None:
        self.add("user", content)

    def add_assistant(self, content: str) -> None:
        self.add("assistant", content)

    def add_system(self, content: str) -> None:
        self.add("system", content)

    def insert(self, index: int, role: str, content: str) -> None:
        if role not in {"user", "assistant", "system"}:
            raise LLMError("Invalid role; expected 'user', 'assistant', or 'system'.")
        self._messages.insert(index, {"role": role, "content": content})

    def edit(self, index: int, *, role: Optional[str] = None, content: Optional[str] = None) -> None:
        m = self._messages[index]
        if role is not None:
            if role not in {"user", "assistant", "system"}:
                raise LLMError("Invalid role; expected 'user', 'assistant', or 'system'.")
            m["role"] = role
        if content is not None:
            if not isinstance(content, str):
                raise LLMError(f"Content must be a string. Got {type(content)}.Content: {content}")
            m["content"] = content

    def delete(self, index: int) -> None:
        del self._messages[index]

    def clear(self) -> None:
        self._messages.clear()

    # ---- accessors ----
    def messages(self) -> List[Message]:
        return list(self._messages)

    def __len__(self) -> int:
        return len(self._messages)

    def __getitem__(self, index: int) -> Message:
        return self._messages[index]

    # ---- formatting ----
    def as_string(
        self,
        model_name: Optional[str] = None,
        *,
        include_system: bool = False,
        add_prompt_stub: bool = True,
        brand_assistant: bool = False,
    ) -> str:
        """
        Returns a string like:
        "User: hi\nAssistant: hello\nUser:\n"
        - If brand_assistant=True and model_name is provided, uses "Assistant (model_name)".
        - include_system optionally shows system messages as 'System: ...'.
        - add_prompt_stub appends trailing 'User:' when last speaker isn't the user.
        """
        lines: List[str] = []
        for m in self._messages:
            role = m["role"]
            if role == "system" and not include_system:
                continue
            if role == "user":
                label = self.user_name
            elif role == "system":
                label = "System"
            else:
                if brand_assistant and model_name:
                    label = f"Assistant ({model_name})"
                else:
                    label = "Assistant"
            lines.append(f"{label}: {m['content']}".rstrip())

        if add_prompt_stub and (not self._messages or self._messages[-1]["role"] != "user"):
            lines.append(f"{self.user_name}:")
        # End with a newline for nicer console rendering
        return "\n".join(lines) + ("\n" if lines else "")


# ---- Base class ------------------------------------------------------------

class LLM(ABC):
    def __init__(
        self,
        model: Optional[str] = None,
        *,
        temperature: float = 0.3,
        timeout: float = 60.0,
        max_retries: int = 2,
        rpm_limit: Optional[int] = None,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self._configured = False
        # in-process per-minute request cap
        self._rpm_limit: Optional[int] = int(rpm_limit) if rpm_limit is not None else None
        self._rpm_window: float = 60.0
        self._rpm_calls: List[float] = []

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
                self._throttle()
                return fn()
            except KeyboardInterrupt:
                raise
            except BaseException as e:
                last_exc = e
                if i >= attempts - 1:
                    break
                time.sleep(min(2 ** i, 8) + 0.05 * i)
        raise LLMError(f"LLM call failed after {attempts} attempt(s): {last_exc}")

    # ---- Rate limit (per-process, per-minute) -------------------------------
    def set_rate_limit(self, rpm: Optional[int]) -> None:
        self._rpm_limit = int(rpm) if rpm is not None else None

    def _throttle(self) -> None:
        if not self._rpm_limit:
            return
        now = time.time()
        # drop timestamps outside the window
        while self._rpm_calls and now - self._rpm_calls[0] >= self._rpm_window:
            self._rpm_calls.pop(0)
        if len(self._rpm_calls) >= self._rpm_limit:
            sleep_for = self._rpm_window - (now - self._rpm_calls[0]) + 0.001
            if sleep_for > 0:
                time.sleep(sleep_for)
            now = time.time()
            while self._rpm_calls and now - self._rpm_calls[0] >= self._rpm_window:
                self._rpm_calls.pop(0)
        self._rpm_calls.append(time.time())


# ---- OpenAI: ChatGPT --------------------------------------------------------

class ChatGPT(LLM):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Optional: quiet OpenAI SDK/native stderr (same pattern as Gemini / Ollama).
        self.quiet: bool = bool(kwargs.pop("quiet", False))
        super().__init__(*args, **kwargs)
        self._openai_client = None
        self._default_reasoning_effort: Optional[str] = None

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

        if timeout is not None:
            self.timeout = float(timeout)

        self._openai_client = OpenAI(
            api_key=api_key,
            timeout=self.timeout or None,
        )

        if model:
            self.model = model
        if temperature is not None:
            self.temperature = float(temperature)
        if not self.model:
            # Default can be overridden by caller.
            self.model = "gpt-5-nano"

        # Default: explicitly disable reasoning for GPT-5.1 family.
        model_l = (self.model or "").lower()
        if "gpt-5" in model_l:
            self._default_reasoning_effort = "minimal"
        else:
            self._default_reasoning_effort = None

        self._configured = True

    def send_msg(
        self,
        messages: Union[str, Message, Sequence[Message]],
        *,
        temperature: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
        quiet: Optional[bool] = None,
        reasoning_effort: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        self._require_configured()
        assert self._openai_client is not None

        msgs = self._normalize_messages(messages)
        chat_messages = [{"role": m["role"], "content": m["content"]} for m in msgs]
        curr_temp = self.temperature if temperature is None else float(temperature)

        # Base request for Responses API.
        req: Dict[str, Any] = {
            "model": self.model,
            "input": chat_messages,
            "temperature": curr_temp,
        }
        if max_output_tokens is not None:
            # For Responses API, the correct limit parameter is max_output_tokens.
            req["max_output_tokens"] = int(max_output_tokens)

        # Decide reasoning_effort to send (if any).
        eff = reasoning_effort if reasoning_effort is not None else self._default_reasoning_effort

        # Only gpt-5* and o-series support the `reasoning` block.
        model_l = (self.model or "").lower()
        is_reasoning_model = (
            model_l.startswith("gpt-5")
            or model_l.startswith("o1")
            or model_l.startswith("o3")
            or model_l.startswith("o4")
        )
        if eff is not None and is_reasoning_model:
            req["reasoning"] = {"effort": eff}

        # Allow advanced/extra options via kwargs without clobbering known keys.
        for k, v in kwargs.items():
            if k not in req:
                req[k] = v

        use_quiet = self.quiet if quiet is None else bool(quiet)

        def _call() -> str:
            with _quiet_ctx(use_quiet):
                # Use Responses API as recommended for reasoning models.
                resp = self._openai_client.responses.create(**req)
            text = getattr(resp, "output_text", None)
            return (text or "").strip()

        return self._with_retry(_call)


# ---- Google: Gemini ---------------------------------------------------------

class Gemini(LLM):
    """
    Gemini client using the new `google-genai` SDK (Google GenAI).

    Env:
      - GEMINI_API_KEY or GOOGLE_API_KEY

    Use quiet=True to suppress native gRPC/absl stderr chatter on init.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.quiet: bool = bool(kwargs.pop("quiet", False))
        super().__init__(*args, **kwargs)
        self._genai_client = None
        self._genai_types = None
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
                from google import genai  # type: ignore
                from google.genai import types  # type: ignore
            except Exception as e:
                raise LLMConfigError(
                    "google-genai not installed. `pip install google-genai`"
                ) from e

            # Honor timeout at client level when possible (milliseconds).
            # Fallback to dict if typed options aren't available.
            http_options = None
            try:
                if timeout is not None:
                    self.timeout = float(timeout)
                if self.timeout is not None:
                    http_options = types.HttpOptions(timeout=int(self.timeout * 1000))
            except Exception:
                if self.timeout is not None:
                    http_options = {"timeout": int(self.timeout * 1000)}  # degrade gracefully

            self._genai_client = genai.Client(api_key=api_key, http_options=http_options)
            self._genai_types = types

            if model:
                self.model = model
            if temperature is not None:
                self.temperature = float(temperature)
            if not self.model:
                self.model = "gemini-2.5-flash"

            self._model_name_cache = self.model
            self._configured = True

    @staticmethod
    def _to_gemini_contents(
        messages: List[Message],
        *,
        types_mod: Any,
    ) -> Tuple[Optional[str], List[Any]]:
        system_parts: List[str] = []
        contents: List[Any] = []
        for m in messages:
            role, text = m["role"], m["content"]
            if role == "system":
                system_parts.append(text)
            elif role == "assistant":
                contents.append(types_mod.Content(role="model", parts=[types_mod.Part.from_text(text=text)]))
            else:  # user
                contents.append(types_mod.Content(role="user", parts=[types_mod.Part.from_text(text=text)]))
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
        assert self._genai_client is not None and self._genai_types is not None

        msgs = self._normalize_messages(messages)
        system_instr, contents = self._to_gemini_contents(msgs, types_mod=self._genai_types)
        curr_temp = self.temperature if temperature is None else float(temperature)

        # Gemma models reject system/developer instructions; inline them as a user message instead.
        model_l = (self._model_name_cache or self.model or "").lower()
        supports_system_instruction = "gemma" not in model_l
        if system_instr and not supports_system_instruction:
            contents = [
                self._genai_types.Content(
                    role="user",
                    parts=[self._genai_types.Part.from_text(text=system_instr)],
                )
            ] + contents
            system_instr = None

        # Build config using typed model; only include provided fields.
        cfg_kwargs: Dict[str, Any] = {"temperature": curr_temp}
        if max_output_tokens is not None:
            cfg_kwargs["max_output_tokens"] = int(max_output_tokens)
        if system_instr:
            cfg_kwargs["system_instruction"] = system_instr

        # Thinking config: 2.5 Pro => 128, other 2.5 (Flash/Light) => 0 (disabled)
        if "2.5" in model_l:
            budget = 128 if "pro" in model_l else 0
            cfg_kwargs["thinking_config"] = self._genai_types.ThinkingConfig(thinking_budget=budget)

        config = self._genai_types.GenerateContentConfig(**cfg_kwargs)

        use_quiet = self.quiet if quiet is None else bool(quiet)

        def _call() -> str:
            with _quiet_ctx(use_quiet):
                resp = self._genai_client.models.generate_content(
                    model=self.model,
                    contents=contents if contents else "",
                    config=config,
                    **kwargs,
                )
            return (getattr(resp, "text", None) or "").strip()

        return self._with_retry(_call)


# ---- Ollama -----------------------------------------------------------------

class Ollama(LLM):
    """
    Simple Ollama client using the local HTTP API (/api/chat).

    Env / config:
      - OLLAMA_BASE_URL  (optional, defaults to "http://localhost:11434")
      - OLLAMA_MODEL     (optional, defaults to "gemma3:1b-it-qat")
      - OLLAMA_NUM_CTX   (optional, context window in tokens; default in code: 8192)
        (fallback env name: CONTEXT)
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.base_url: str = kwargs.pop(
            "base_url",
            os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        ).rstrip("/")

        # Default context window (tokens). Override via env or per-request.
        # - Env: OLLAMA_NUM_CTX (preferred), or CONTEXT (fallback)
        _env_num_ctx = os.getenv("OLLAMA_NUM_CTX") or os.getenv("CONTEXT")
        self.num_ctx: int = int(_env_num_ctx) if _env_num_ctx else 8192

        super().__init__(*args, **kwargs)

    def config_api(
        self,
        *,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        timeout: Optional[float] = None,
        num_ctx: Optional[int] = None,
    ) -> None:
        if base_url:
            self.base_url = base_url.rstrip("/")

        if model:
            self.model = model

        if temperature is not None:
            self.temperature = float(temperature)

        if timeout is not None:
            self.timeout = float(timeout)

        if num_ctx is not None:
            self.num_ctx = int(num_ctx)

        if not self.model:
            self.model = os.getenv("OLLAMA_MODEL", "gemma3:1b-it-qat")

        if not self.model:
            raise LLMConfigError("Missing Ollama model name (set OLLAMA_MODEL or pass model=...).")

        self._configured = True

    def send_msg(
        self,
        messages: Union[str, Message, Sequence[Message]],
        *,
        temperature: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
        num_ctx: Optional[int] = None,
        quiet: Optional[bool] = None,  # kept for interface compatibility
        **kwargs: Any,
    ) -> str:
        self._require_configured()

        chat_messages = self._normalize_messages(messages)
        curr_temp = temperature if temperature is not None else self.temperature

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": chat_messages,
            # IMPORTANT: no streaming, single JSON response
            "stream": False,
        }

        options: Dict[str, Any] = {}
        if curr_temp is not None:
            options["temperature"] = float(curr_temp)
        if max_output_tokens is not None:
            # Ollama uses "num_predict" for max output tokens
            options["num_predict"] = int(max_output_tokens)

        use_num_ctx = self.num_ctx if num_ctx is None else int(num_ctx)
        if use_num_ctx is not None:
            options["num_ctx"] = int(use_num_ctx)

        if options:
            payload["options"] = options

        # Allow advanced/extra options via kwargs (without clobbering known keys)
        for k, v in kwargs.items():
            if k not in payload:
                payload[k] = v

        data = json.dumps(payload).encode("utf-8")
        url = f"{self.base_url}/api/chat"
        headers = {"Content-Type": "application/json"}

        def _call() -> str:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout or None) as resp:
                    body = resp.read().decode("utf-8")
            except urllib.error.HTTPError as e:
                err_body = ""
                try:
                    err_body = e.read().decode("utf-8")
                except Exception:
                    pass
                raise LLMConfigError(
                    f"Ollama HTTP {e.code}: {e.reason} {err_body}"
                ) from e
            except Exception as e:
                raise LLMConfigError(f"Ollama request failed: {e}") from e

            # 1) First, try standard non-streaming JSON: {"message": {"content": "..."}}
            try:
                obj = json.loads(body)
            except Exception:
                # 2) Fallback: handle NDJSON streaming output if stream=True ever gets used
                chunks: List[str] = []
                for line in body.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        part = json.loads(line)
                    except Exception:
                        continue
                    msg = part.get("message") or {}
                    if isinstance(msg, dict):
                        c = msg.get("content")
                        if isinstance(c, str):
                            chunks.append(c)
                if chunks:
                    return "".join(chunks).strip()
                return body.strip()

            text: Optional[str] = None

            if isinstance(obj, dict):
                # Normal /api/chat response
                msg = obj.get("message")
                if isinstance(msg, dict) and isinstance(msg.get("content"), str):
                    text = msg["content"]

                # /api/generate-style fallback: {"response": "..."}
                if text is None and isinstance(obj.get("response"), str):
                    text = obj["response"]

                # Some variants expose "messages": [...]
                if text is None:
                    msgs = obj.get("messages")
                    if isinstance(msgs, list) and msgs:
                        last = msgs[-1]
                        if isinstance(last, dict) and isinstance(last.get("content"), str):
                            text = last["content"]

            # Last-resort: raw body
            if text is None:
                text = body

            return text.strip()

        return self._with_retry(_call)

# ---- Smoke test / CLI ------------------------------------------------------

if __name__ == "__main__":
    # Example Gemini interactive loop
    try:
        chat = Gemini(model="gemini-2.5-flash", quiet=True)
        chat.config_api()  # reads GEMINI_API_KEY / GOOGLE_API_KEY

        mem = ChatMemory()

        # Clear console
        os.system("cls" if os.name == "nt" else "clear")
        while True:
            msg = input("You: ")
            if msg.strip().lower() in {"exit", "quit"}:
                break

            # keep history and send the whole conversation
            mem.add_user(msg)
            reply = chat.send_msg(mem.messages())
            mem.add_assistant(reply)

            # dynamic model label (class name) to keep output format like "Gemini: ..."
            print(f"{chat.__class__.__name__}:", reply)

            # If you ever need the string history:
            # print(mem.as_string(chat.__class__.__name__, brand_assistant=True))
    except Exception as e:
        print("[Gemini error]", e)

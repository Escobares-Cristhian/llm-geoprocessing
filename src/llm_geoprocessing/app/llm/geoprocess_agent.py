import json
import re
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from pathlib import Path
import subprocess
import shutil
import requests
import os
from datetime import datetime

from llm_geoprocessing.app.chatbot.chatbot import Chatbot
from llm_geoprocessing.app.plugins.preprocessing_plugin import get_metadata_preprocessing, get_documentation_preprocessing
from llm_geoprocessing.app.plugins.geoprocessing_plugin import get_metadata_geoprocessing, get_documentation_geoprocessing
from llm_geoprocessing.app.plugins.runtime_executor import execute_action

# ---------------------------------
# ----- JSON Completion Logic -----
# ---------------------------------

class PluginInstructions:
    def __init__(self) -> None:
        self._cache: Optional[str] = None  # internal txt

    def __call__(self) -> str:
        # If already built, return the saved txt.
        if self._cache is not None:
            return self._cache

        # Information about available data and preprocessing
        data_metadata = get_metadata_preprocessing()
        data_docs = get_documentation_preprocessing()
        
        # Information about geoprocessing capabilities
        geoprocess_metadata = get_metadata_geoprocessing()
        geoprocess_docs = get_documentation_geoprocessing()
        
        # Combine to get instructions to append to the schema instructions
        plugin_instructions = (
            "Available Data and Preprocessing Options:\n"
            f"{data_metadata}\n"
            f"{data_docs}\n\n"
            "Geoprocessing Capabilities:\n"
            f"{geoprocess_metadata}\n"
            f"{geoprocess_docs}\n\n"
            "General Notes:\n"
            "- Use ONLY information present in: (1) the provided summary text, (2) the sections above.\n"
            "- If a geoprocess is requested but required data/params/capabilities are missing, add precise questions in 'questions'.\n"
            "- Do not assume availability of any data or capability not explicitly listed above.\n"
            "- Do not invent filenames, paths, dates, projections, resolutions, parameters, or function names. Use only the ones explicitly mentioned in 'Available Data and Preprocessing Options' or 'Geoprocessing Capabilities'\n"
        )

        # Persist once in memory, then return.
        self._cache = plugin_instructions
        return plugin_instructions
    
# Initialize plugin instructions as a singleton
_plugin_instructions = PluginInstructions()

def _schema_instructions() -> str:
    # Strict schema + rules (concise)
    schema = (
        "Return ONLY a JSON wrapper with keys: 'json', 'complete', 'questions'.\n"
        "- 'json' keys:\n"
        "  1) 'products': object mapping product IDs ('A','B',...) to objects. List of dicts with keys:\n"
        "     - 'id': string (unique ID for this product). Obligatory.\n"
        "     - 'name': string (full product path; must be a file, not a folder). Obligatory.\n"
        "     - 'date': {'initial_date':'YYYY-MM-DD','end_date':'YYYY-MM-DD'} Obligatory.\n"
        "     - 'proj': string (use 'default' to keep original). Obligatory.\n"
        "     - 'res': number OR the string 'default' to keep original. Obligatory.\n"
        "     - If no products are needed, use an empty list [].\n"
        "  2) 'actions': list of dicts, each with keys:\n"
        "     - 'geoprocess_name': string (must be listed in 'Geoprocessing Capabilities').\n"
        "     - 'input_json': object with ONLY required parameters; {} if none.\n"
        "     - 'output_id': string unique identifier for this step's output, must be created by you and not by the user.\n"
        "     List multiple geoprocesses in execution order, or [] if no geoprocessing is requested.\n"
        "  3) 'other_params': dict of global parameters ({} if not needed, but must have this key).\n"
        "     Global parameters for the Geoprocessing Capabilities."
        "     If no global parameters are needed, use an empty object {}."
        "     If no global parameters are specified in the Geoprocessing Capabilities, use an empty object {}.\n"
        "Constraints:\n"
        "- Never invent values. Use ONLY facts found in the provided summary and capability lists.\n"
        "- If any required value is unknown or missing, omit it from 'json' and set 'complete': false; add precise questions.\n"
        "- Output MUST be minified JSON (single object), with no trailing commas and no extra keys.\n"
        "- Only assume information when the user explicitly asks to assume it.\n"
        "- 'products' and 'actions' cannot be empty lists; if no products or actions are requested, then ask questions instead.\n"
        "Change Mode (if the user requests modifications and a prior JSON exists anywhere in the conversation):\n"
        "- Treat the most recent valid JSON as the authoritative baseline ('TRUTH').\n"
        "- Apply ONLY the user's requested changes. Keep all other values exactly as-is.\n"
        "- Do NOT ask questions about unchanged parts. Ask questions ONLY if the requested change itself is ambiguous.\n"
        "- Prefer appending or minimally editing structures (e.g., actions) unless the user explicitly asks to replace.\n"
        "Wrapper format exactly:\n"
        "{ 'json': {...}, 'complete': true|false, 'questions': ['Q1','Q2',...] }\n"
    )
    
    return _plugin_instructions() + "\n\n" + schema


def _sanitize_json(raw: str) -> str:
    # Replace bare NaN -> "NaN"; remove trailing commas
    s = re.sub(r'(?<!\")\bNaN\b(?!\")', '"NaN"', raw)
    s = re.sub(r",\s*([}\]])", r"\1", s)
    return s


def _extract_first_json_block(text: str) -> Optional[Dict[str, Any]]:
    # Prefer fenced code blocks
    blocks = re.findall(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text, flags=re.IGNORECASE)
    if not blocks:
        blocks = re.findall(r"(\{[\s\S]*\})", text)
    for b in blocks:
        try:
            return json.loads(_sanitize_json(b))
        except Exception:
            continue
    return None


def complete_json(chatbot: Chatbot, user_message: str) -> Tuple[Chatbot, Dict[str, Any] | str]:
    """
    Build the target JSON by dialog with the user via the LLM.
    - Input: chatbot instance and single pre-processed message (string).
    - Flow: extract -> if missing, ask -> update -> repeat.
    - Output: Python dict with the requested schema.
    - All user-facing messages are generated by the LLM (printed).
    """
    summary_instructions = f"""STRICT USER-ONLY EXTRACT FOR GEOPROCESSING

SCOPE
- Consider ONLY messages with role == "user". Ignore assistant/system content.
- Exception ONLY for the section 'Last JSON instructions generated' (see below).

GOAL
- Produce a compact, evidence-bound summary of the user's request so a downstream step can build:
  products, actions (in order) and other_params.

HARD RULES
- DO NOT ASSUME anything. Use only explicit user text.
- Do not invent filenames, paths, dates, projections, resolutions, parameters, or function names.
- If something is not explicitly stated, write 'not mentioned'.
- Keep user wording for tool/process names; do NOT normalize to internal capability names here.
- For every bullet, include a short verbatim quote as evidence (except the 'Last JSON' section).

OUTPUT (exact order; use bullets exactly as shown)

- Requested products:
  • name: <full path or 'not mentioned'> ; date.initial: <YYYY-MM-DD or 'not mentioned'> ; date.end: <YYYY-MM-DD or 'not mentioned'> ; proj: <value or 'not mentioned'> ; res: <number|'default'|'not mentioned'> — evidence: "<verbatim>" (msg #<index>)
  • ...

- Requested actions (execution order):
  • geoprocess_name: <as written by user> ; input_params: {{k: v, ... only those explicitly given}} ; output_id: <explicit or 'not mentioned'> — evidence: "<verbatim>" (msg #<index>)
  • ...

- Other/global parameters:
  • <param_name>: <value> — evidence: "<verbatim>" (msg #<index>)
  • ...

- Constraints & preferences:
  • <constraint or preference exactly as written> — evidence: "<verbatim>" (msg #<index>)
  • ...

- Assumptions explicitly authorized by the user:
  • <assumption> — evidence: "<verbatim>" (msg #<index>)
  • ...

- Last JSON instructions generated:
  • If a previous JSON instructions exists anywhere in the conversation, paste it VERBATIM here (minified). Do NOT alter or summarize it.
  • If none (or not accessible due to user-only scope), write: none

- Important context:
  • <other relevant details impacting geoprocessing> — evidence: "<verbatim>" (msg #<index>)
  • ...

STYLE & LENGTH
- One idea per bullet; keep each bullet ≤120 characters (excluding the evidence).
- Evidence is required for all bullets EXCEPT 'Last JSON instructions generated'.
- If a section has no items, write:  • none
- Use ISO dates (YYYY-MM-DD) if the user provided dates.
- Write in the user's language.

TASK
Summarize the current chat messages and this new message:
'{user_message}'
with the key information needed to build geoprocessing JSON instructions as per this schema:
'{_schema_instructions()}'
Return ONLY the sections described in OUTPUT: 'Requested products', 'Requested actions', 'Other/global parameters', 'Constraints & preferences', 'Assumptions explicitly authorized by the user', 'Last JSON instructions generated', and 'Important context'. Nothing else."""

    # Clone chatbot to avoid modifying the original
    chat = chatbot.clone(instructions_to_add=summary_instructions)
    
    MAX_TURNS = 8  # tiny safety to avoid infinite loops

    # 1) Ask LLM to extract from the initial message
    prompt = (
        "Task: Extract everything you can from the user's message into the schema. "
        "If the user is requesting changes to an existing JSON, locate the most recent JSON present "
        "anywhere in this conversation (system, assistant or user messages) and treat it as the authoritative "
        "baseline ('TRUTH'). Apply ONLY the requested changes, keeping all other fields intact. "
        "Do NOT ask questions about unchanged parts; ask ONLY if the requested change itself is ambiguous.\n\n"
        f"User message:\n{user_message}\n\nSchema instructions:\n{_schema_instructions()}"
    )
    reply = chat.send_message(prompt)
    wrapper = _extract_first_json_block(reply)
    if not wrapper or not all(k in wrapper for k in ("json", "complete", "questions")):
        raise ValueError("LLM did not return a valid wrapper JSON on first pass.")

    state: Dict[str, Any] = wrapper["json"]
    complete: bool = bool(wrapper["complete"])
    questions: List[str] = list(wrapper.get("questions", []))

    # 2) If incomplete, iterate: ask -> wait -> update
    turns = 0
    while not complete and turns < MAX_TURNS:
        turns += 1

        # LLM composes the concise questions to show the user
        q_prompt = (
            "Compose a single concise message asking ONLY these questions in bullet list, nothing else.\n"
            "Ask ONLY about ambiguities in the requested changes. "
            "Do not repeat yourself in the questions, so do not ask '¿What is the resolution for the map in <location>?' and '¿What is the projection for the map in <location>?', instead as 'For the map in <location>, clarify these details: \\n- resolution: <small explaining of the information needed>\\n- projection: <small explaining of the information needed>'.\n"
            "If you cannot bind questions like that, then ask them separately, but always try to minimize the number of questions asked collapsing them when possible (but maintaining bullet list format and sub-bullets when needed).\n"
            "Do NOT include questions about anything present in the baseline JSON that the user did not ask to change.\n"
            + "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions))
            + "\n Respond in the same language as the user."
        )
        q_msg = chat.send_message(q_prompt)
        print(f"{chat.chat.__class__.__name__}: {q_msg}") # show LLM's question to the user
        # Save assistant response in to original chat history
        chatbot.mem.add_assistant(q_msg)

        # Get user answers
        valid_user_answer = False
        while not valid_user_answer:
            user_answer = input("You: ").strip()

            # Check for commands
            command = chat.check_command(user_answer)
            if command == "exit":
                return chatbot, "exit"
            elif command == "ask for input":
                continue  # ask again
            elif command:
                print(command) # print command output and ask again
                continue
            
            valid_user_answer = True

        # Save user answer in to original chat history
        chatbot.mem.add_user(user_answer)

        # Ask LLM to update the JSON with the user's answers
        update_prompt = (
            "Update the JSON with the user's answers. Keep confirmed fields. "
            "Use the most recent JSON in this conversation as the authoritative baseline ('TRUTH') "
            "unless the user explicitly asked to change those parts. Apply ONLY the requested changes. "
            "Ask follow-ups ONLY to disambiguate those changes.\n"
            "Do not assume information unless when the user ask to assume.\n"
            "Assume information only when the user is clearly a non expert (not use of technical language, vague, unsure, etc).\n"
            "If information is indirect but clear, you can assume it. An example for dates, if the user says '... mean from autumn to winter ...', you can assume the initial date and end date accordingly. An example for resolutions, if the user says '... high resolution ...', you can assume the highest native resolution available for that product. An example for products, if the user says '... I do not know...' (referring to a product), you can assume the most suitable product available for the requested geoprocess.\n"
            "Never said to user that he/she is an expert or not.\n\n"
            f"Current JSON:\n```json\n{json.dumps(state, ensure_ascii=False)}\n```\n\n"
            f"User reply:\n{user_answer}\n\n{_schema_instructions()}"
        )
        reply = chat.send_message(update_prompt)
        wrapper = _extract_first_json_block(reply)
        if not wrapper or not all(k in wrapper for k in ("json", "complete", "questions")):
            raise ValueError("LLM did not return a valid wrapper JSON during update.")

        state = wrapper["json"]
        complete = bool(wrapper["complete"])
        questions = list(wrapper.get("questions", []))
        
        # DEBUG
        print("+"*60)
        # print wrapper
        print("Current JSON state:")
        print(json.dumps(state, ensure_ascii=False, indent=2))
        print(f"Complete: {complete}")
        print(f"Questions:")
        for q in questions:
            print(f"- {q}")
        print("+"*60)

    state = check_and_fix_json(chat, state, hierarchy=0, max_hierarchy=10)

    return chatbot, state

def HandleValueErrorWithLLM(chatbot: Chatbot, state: Dict[str, Any], error_msg: str) -> Dict[str, Any]:
    """
    Handle ValueError exceptions by asking the LLM to fix the issue.
    """
    # Build prompt to ask LLM to fix the issue
    fix_prompt = (
        "The current JSON has the following issue:\n"
        f"{error_msg}\n\n"
        "Please fix the JSON accordingly, keeping all other fields intact. "
        "If you cannot fix it due to missing information, set 'complete': false and add precise questions.\n\n"
        f"Current JSON:\n```json\n{json.dumps(state, ensure_ascii=False)}\n```\n\n"
        f"{_schema_instructions()}"
    )
    reply = chatbot.send_message(fix_prompt)
    wrapper = _extract_first_json_block(reply)
    if not wrapper or not all(k in wrapper for k in ("json", "complete", "questions")):
        raise ValueError("LLM did not return a valid wrapper JSON during error handling.")

    return wrapper["json"]

def check_and_fix_json(
    chatbot: Chatbot,
    state: Dict[str, Any],
    hierarchy: int,
    max_hierarchy: int,
    *,
    error_attempts: Optional[Dict[str, int]] = None,
    max_hierarchy_per_error: int = 3,
) -> Dict[str, Any]:
    """
    Recursive JSON checker/fixer:
    - Tries to validate `state`.
    - On any ValueError, asks the LLM to fix it and retries recursively.
    - Stops when either `max_hierarchy` is reached globally, or a specific error
      exceeds `max_hierarchy_per_error`.
    """

    if hierarchy >= max_hierarchy:
        raise ValueError("Maximum JSON correction hierarchy reached.")

    if error_attempts is None:
        error_attempts = {}

    def _normalize_error_key(msg: str) -> str:
        # Bucket similar errors together by stripping indices, quoted values, and numbers.
        # This keeps the per-error counter meaningful with minimal code.
        k = re.sub(r"'[^']*'", "''", msg)      # remove quoted specifics
        k = re.sub(r"\d+", "#", k)             # replace digits
        k = re.sub(r"\s+", " ", k).strip()     # collapse spaces
        return k

    def _retry_with_llm(err_msg: str) -> Dict[str, Any]:
        key = _normalize_error_key(err_msg)
        cnt = error_attempts.get(key, 0)
        if cnt >= max_hierarchy_per_error:
            raise ValueError(f"Exceeded attempts for error: {key} (limit={max_hierarchy_per_error})")
        error_attempts[key] = cnt + 1

        fixed = HandleValueErrorWithLLM(chatbot, state, err_msg)
        return check_and_fix_json(
            chatbot,
            fixed,
            hierarchy=hierarchy + 1,
            max_hierarchy=max_hierarchy,
            error_attempts=error_attempts,
            max_hierarchy_per_error=max_hierarchy_per_error,
        )

    try:
        # ----------------------------
        # Minimal shape checks (simple and strict)
        # ----------------------------
        required = ["products", "actions", "other_params"]  # per-product date/proj/res now nested
        if not all(k in state for k in required):
            missing_keys = [k for k in required if k not in state]
            raise ValueError(f"Final JSON missing required keys: {missing_keys}")

        # Disallow unexpected top-level keys
        extra_keys = set(state.keys()) - set(required)
        if extra_keys:
            raise ValueError(f"Final JSON has unexpected keys: {sorted(extra_keys)}")

        # products MUST be a list of product objects (each with a unique 'id')
        products = state.get("products")
        if not (isinstance(products, list) and all(isinstance(p, dict) for p in products)):
            raise ValueError("'products' must be a list of product objects.")

        actions = state.get("actions")
        if not (isinstance(actions, list) and all(isinstance(a, dict) for a in actions)):
            raise ValueError("'actions' must be a list of dicts.")

        if not isinstance(state["other_params"], dict):
            raise ValueError("'other_params' must be a dict.")

        # Per-product validation
        date_pat = re.compile(r"^\d{4}-\d{2}-\d{2}$")

        def _parse_date(s: str) -> datetime:
            return datetime.strptime(s, "%Y-%m-%d")

        seen_product_ids = set()
        # If not empty products, check each product
        if state["products"]:
            for idx, pobj in enumerate(state["products"]):
                if not isinstance(pobj, dict):
                    raise ValueError(f"Product at index {idx} must be an object.")

                # must include required fields
                for k in ("id", "name", "date", "proj", "res"):
                    if k not in pobj:
                        raise ValueError(f"Product at index {idx} missing '{k}'.")

                if not (isinstance(pobj["id"], str) and pobj["id"]):
                    raise ValueError(f"Product at index {idx}.id must be a non-empty string.")
                if pobj["id"] in seen_product_ids:
                    raise ValueError(f"Duplicate product id '{pobj['id']}'.")
                seen_product_ids.add(pobj["id"])

                if not isinstance(pobj["name"], str):
                    raise ValueError(f"Product '{pobj['id']}'.name must be a string.")
                base = pobj["name"].rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
                if not base or base.endswith(("/", "\\")):
                    raise ValueError(f"Product '{pobj['id']}'.name must be a file path (not a folder).")

                if not isinstance(pobj["proj"], str):
                    raise ValueError(f"Product '{pobj['id']}'.proj must be a string.")

                if not ((isinstance(pobj["res"], (int, float)) and not isinstance(pobj["res"], bool)) or pobj["res"] == "default"):
                    raise ValueError(f"Product '{pobj['id']}'.res must be a float or 'default'.")

                if not isinstance(pobj["date"], dict):
                    raise ValueError(f"Product '{pobj['id']}'.date must be a dict.")
                if set(pobj["date"].keys()) != {"initial_date", "end_date"}:
                    raise ValueError(f"Product '{pobj['id']}'.date must have 'initial_date' and 'end_date'.")

                di = pobj["date"]["initial_date"]
                de = pobj["date"]["end_date"]
                if not (isinstance(di, str) and date_pat.match(di)):
                    raise ValueError(f"Product '{pobj['id']}'.date['initial_date'] must be 'YYYY-MM-DD'.")
                if not (isinstance(de, str) and date_pat.match(de)):
                    raise ValueError(f"Product '{pobj['id']}'.date['end_date'] must be 'YYYY-MM-DD'.")
                if _parse_date(di) > _parse_date(de):
                    raise ValueError(f"Product '{pobj['id']}' has initial_date after end_date.")

            # Actions: list of objects with required keys and unique output_id
            known_ids = set(seen_product_ids)  # products usable by product_id
            seen_outputs = set()

            for i, act in enumerate(state["actions"]):
                if not isinstance(act, dict):
                    raise ValueError(f"'actions[{i}]' must be an object.")
                for k in ("geoprocess_name", "input_json", "output_id"):
                    if k not in act:
                        raise ValueError(f"'actions[{i}]' missing '{k}'.")

                gname = act["geoprocess_name"]
                params = act["input_json"]
                out_id = act["output_id"]

                if not (isinstance(gname, str) and gname):
                    raise ValueError(f"'actions[{i}].geoprocess_name' must be a non-empty string.")
                if not isinstance(params, dict):
                    raise ValueError(f"'actions[{i}].input_json' must be an object.")
                if not (isinstance(out_id, str) and out_id):
                    raise ValueError(f"'actions[{i}].output_id' must be a non-empty string.")
                if out_id in seen_outputs:
                    raise ValueError(f"Duplicate output_id in actions: '{out_id}'.")

                # id references must exist (product or prior output)
                def _must_exist(v: str, label: str):
                    if not isinstance(v, str):
                        raise ValueError(f"'actions[{i}].input_json.{label}' must be a string.")
                    if v not in known_ids:
                        raise ValueError(f"'actions[{i}]' references unknown id '{v}' in '{label}'.")

                if "product_id" in params:
                    _must_exist(params["product_id"], "product_id")
                if "product_id1" in params:
                    _must_exist(params["product_id1"], "product_id1")
                if "product_id2" in params:
                    _must_exist(params["product_id2"], "product_id2")

                # Optional structural checks
                if "bbox" in params:
                    bbox = params["bbox"]
                    if not (isinstance(bbox, list) and len(bbox) == 4 and all(isinstance(x, (int, float)) for x in bbox)):
                        raise ValueError(f"'actions[{i}].input_json.bbox' must be a list of 4 numbers.")
                if "geodesic" in params and not isinstance(params["geodesic"], bool):
                    raise ValueError(f"'actions[{i}].input_json.geodesic' must be boolean.")
                if "date_initial" in params:
                    di = params["date_initial"]
                    if not (isinstance(di, str) and date_pat.match(di)):
                        raise ValueError(f"'actions[{i}].input_json.date_initial' must be 'YYYY-MM-DD'.")
                if "date_end" in params:
                    de = params["date_end"]
                    if not (isinstance(de, str) and date_pat.match(de)):
                        raise ValueError(f"'actions[{i}].input_json.date_end' must be 'YYYY-MM-DD'.")
                if "date_initial" in params and "date_end" in params:
                    if _parse_date(params["date_initial"]) > _parse_date(params["date_end"]):
                        raise ValueError(f"'actions[{i}]' has date_initial after date_end.")

                # Register this action's output for subsequent references
                seen_outputs.add(out_id)
                known_ids.add(out_id)

        return state

    except ValueError as e:
        # All validation errors flow through here.
        return _retry_with_llm(str(e))


# -------------------------------
# ----- Geoprocessing Logic -----
# -------------------------------

# --- Local download & GDAL merge helpers -------------------------------------

# Fixed base output directory (change here or via env var GEO_OUT_DIR)
OUTPUT_BASE_DIR = Path(os.getenv("GEO_OUT_DIR", "/tmp"))
TILES_ROOT      = OUTPUT_BASE_DIR / "gee_tiles"
MERGED_ROOT     = OUTPUT_BASE_DIR / "gee_merged"

def _debug_env():
    print(f"[DEBUG] PATH={os.environ.get('PATH','')}")
    print(f"[DEBUG] GEO_OUT_DIR={OUTPUT_BASE_DIR}")
    print(f"[DEBUG] CWD={os.getcwd()}")
    print(f"[DEBUG] gdalbuildvrt={shutil.which('gdalbuildvrt')}")
    print(f"[DEBUG] gdal_translate={shutil.which('gdal_translate')}")
    print(f"[DEBUG] TILES_ROOT={TILES_ROOT} exists? {TILES_ROOT.exists()}")
    print(f"[DEBUG] MERGED_ROOT={MERGED_ROOT} exists? {MERGED_ROOT.exists()}")

def _print_tree(root: Path, depth: int = 2):
    try:
        root = Path(root)
        print(f"[DEBUG] Tree: {root} (depth={depth})")
        if not root.exists():
            print("  (does not exist)")
            return
        def _walk(d: Path, level: int = 0):
            if level > depth: return
            for p in sorted(d.iterdir()):
                print("  " * level + f"- {p.name}")
                if p.is_dir(): _walk(p, level + 1)
        _walk(root, 0)
    except Exception as e:
        print(f"[DEBUG] tree error for {root}: {e}")

def _ensure_outdirs() -> None:
    TILES_ROOT.mkdir(parents=True, exist_ok=True)
    MERGED_ROOT.mkdir(parents=True, exist_ok=True)

def _clean_dir(p: Path) -> None:
    if p.exists():
        for child in p.iterdir():
            if child.is_file() or child.is_symlink():
                child.unlink(missing_ok=True)
            elif child.is_dir():
                shutil.rmtree(child)
    else:
        p.mkdir(parents=True, exist_ok=True)

def _download_file(url: str, dest: Path, timeout: int = 300) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
    size = dest.stat().st_size
    print(f"[DEBUG] saved {dest} ({size} bytes)")
    return dest

def _download_tiles(urls: list[str], tiles_dir: Path, stem: str) -> list[Path]:
    _clean_dir(tiles_dir)  # avoid mixing old tiles
    out_paths: list[Path] = []
    for i, u in enumerate(urls, 1):
        # always write .tif — GEE endpoints here return GeoTIFF for /tif/* routes
        p = tiles_dir / f"{stem}_tile_{i:02d}.tif"
        _download_file(u, p)
        out_paths.append(p)
    return out_paths

def _require_gdal() -> tuple[str, str]:
    vb = shutil.which("gdalbuildvrt")
    gt = shutil.which("gdal_translate")
    print(f"[DEBUG] which gdalbuildvrt -> {vb}")
    print(f"[DEBUG] which gdal_translate -> {gt}")
    if not vb or not gt:
        raise RuntimeError(
            "GDAL not found. Install gdal (gdalbuildvrt, gdal_translate) in PATH."
        )
    return vb, gt

def _merge_with_gdal(src_files: list[Path], out_tif: Path) -> Path:
    vb, gt = _require_gdal()
    out_tif.parent.mkdir(parents=True, exist_ok=True)

    # add timestamp to avoid overwrites
    ts = datetime.now().strftime("timestamp-%Y-%m-%d-%H-%M-%S-%f")
    out_path = out_tif.with_name(f"{out_tif.stem}_{ts}{out_tif.suffix}")

    if len(src_files) == 1:
        # single tile: copy as final result
        shutil.copy2(src_files[0], out_path)
        return out_path

    vrt = out_path.with_suffix(".vrt")
    # build VRT
    subprocess.run(
        [vb, str(vrt), *[str(p) for p in src_files]],
        check=True
    )
    # translate to GeoTIFF
    subprocess.run(
        [gt, str(vrt), str(out_path)],
        check=True
    )
    # optional cleanup
    vrt.unlink(missing_ok=True)
    return out_path

# -----------------------------------------------------------------------------

# --- Main geoprocessing function -------------------------------------------------

def geoprocess(json_instructions) -> str:
    """
    Execute the JSON geoprocess instructions without coupling to a specific plugin.

    Strategy:
    - Use a runtime executor that discovers the active plugin (env var or default GEE HTTP adaptor).
    - For each action in order, execute and collect output URLs by 'output_id'.
    """

    products = json_instructions.get("products") or []
    if not isinstance(products, list):
        return "Error: 'products' must be a list."
    
    actions = json_instructions.get("actions") or []
    if not isinstance(actions, list) or not actions:
        return "No geoprocess actions to run."

    _debug_env()
    # _print_tree(OUTPUT_BASE_DIR, depth=2)

    # Build product mapping from id -> name for easy resolution
    product_map = {p.get("id"): p.get("name") for p in products if p.get("id") and p.get("name")}

    outputs = {}
    for idx, action in enumerate(actions, 1):
        name = action.get("geoprocess_name")
        params = action.get("input_json") or {}
        out_id = action.get("output_id") or f"step_{idx}"
        if not name:
            return f"Action #{idx} missing 'geoprocess_name'."

        # Resolve product id to actual product name
        if "product" in params and params["product"] in product_map:
            params["product"] = product_map[params["product"]]
        
        # Execute action
        try:
            result = execute_action(name, params)
        except Exception as e:
            return f"Action '{name}' failed: {e}"

        # Collect URLs from result (tiled or single)
        urls = None
        if isinstance(result, dict):
            if result.get("output_urls"):
                urls = list(result["output_urls"])
            elif result.get("output_url"):
                urls = [result["output_url"]]
            elif result.get("tif_url"):
                urls = [result["tif_url"]]
            elif result.get("url"):
                urls = [result["url"]]
                
        # Print urls for this action
        print(f"Action '{name}' produced {len(urls) if urls else 0} output URLs. Downloading and merging...")
        print(f"[DEBUG] tiles_dir={TILES_ROOT / out_id}")
        print(f"[DEBUG] merged_tif={MERGED_ROOT / (out_id + '.tif')}")

        # Download to fixed path and merge with GDAL
        if urls:
            _ensure_outdirs()
            tiles_dir = TILES_ROOT / out_id
            merged_tif = MERGED_ROOT / f"{out_id}.tif"
            try:
                local_tiles = _download_tiles(urls, tiles_dir, out_id)
                print(f"[DEBUG] downloaded {len(local_tiles)} tiles to {tiles_dir}")
                _print_tree(tiles_dir, depth=1)

                final_path = _merge_with_gdal(local_tiles, merged_tif)
                print(f"[DEBUG] merged -> {final_path}")
                outputs[out_id] = [str(final_path)]
            except Exception as e:
                return f"Action '{name}' download/merge failed: {e}"
        else:
            outputs[out_id] = ["<no file>"]

    # Minimal, focused summary for the interpreter
    lines = ["Geoprocessing completed:"]
    for k, url_list in outputs.items():
        if len(url_list) == 1:
            lines.append(f"- {k}: {url_list[0]}")
        else:
            lines.append(f"- {k} (tiles: {len(url_list)}):")
            for i, u in enumerate(url_list, 1):
                lines.append(f"  {i:02d}. {u}")
    return "\n".join(lines)


# ----------------
# ----- Main -----
# ----------------

def main(chatbot: Chatbot, msg: str) -> Tuple[Chatbot, str] | str:
    print("Entered Geoprocessing Mode...")
    
    # Build JSON instructions via dialog
    chatbot, json_instructions = complete_json(chatbot, msg)
    
    # Handle exit command
    if json_instructions == "exit":
        return "exit"
    
    print("*"*60)
    print("Final JSON instructions:")
    print(json.dumps(json_instructions, ensure_ascii=False, indent=2))
    print("*"*60)
    # Save JSON generation in chat history
    chatbot.mem.add_assistant(f"Generated JSON instructions:\n{json.dumps(json_instructions, ensure_ascii=False, indent=2)}")

    msg_to_interpreter = geoprocess(json_instructions)
    
    return chatbot, msg_to_interpreter

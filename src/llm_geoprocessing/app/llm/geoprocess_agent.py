import json
import re
from typing import Dict, Any, List, Optional
from datetime import datetime

from llm_geoprocessing.app.chatbot.chatbot import Chatbot
from llm_geoprocessing.app.plugins.preprocessing_plugin import get_metadata_preprocessing, get_documentation_preprocessing
from llm_geoprocessing.app.plugins.geoprocessing_plugin import get_metadata_geoprocessing, get_documentation_geoprocessing

    
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
        "     - 'id': string (unique ID for this product).\n"
        "     - 'name': string (full product path; must be a file, not a folder).\n"
        "     - 'date': {'initial_date':'YYYY-MM-DD','end_date':'YYYY-MM-DD'}\n"
        "     - 'proj': string (use 'default' to keep original).\n"
        "     - 'res': number OR the string 'default' to keep original.\n"
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


def complete_json(chatbot: Chatbot, user_message: str) -> Dict[str, Any]:
    """
    Build the target JSON by dialog with the user via the LLM.
    - Input: chatbot instance and single pre-processed message (string).
    - Flow: extract -> if missing, ask -> update -> repeat.
    - Output: Python dict with the requested schema.
    - All user-facing messages are generated by the LLM (printed).
    """
    # summary_instructions = "Summarize the current chat messages, focusing on geoprocessing tasks & data explicitly mentioned to respond this user message:\n"
    # summary_instructions += f"'{user_message}'\n"
    # summary_instructions += "Do not summarize messages from the Assistant, only the information provided by the User.\n"
    # summary_instructions += "Keep it concise in each bullet, but make all the bullets you need to cover all relevant details explicitly mentioned. "
    # summary_instructions += "DO NOT ASSUME ANY INFORMATION. USE INFORMATION EXPLICITLY MENTIONED IN THE PREVIOUS MESSAGES."
    # summary_instructions += "Keep the important details about products, actions, and parameters discussed."
    # summary_instructions += "Use this format:\n"
    # summary_instructions += "- Unwanted details: <list of things that the user explicitly does NOT want>\n"
    # summary_instructions += "- Desired details: <list of things that the user explicitly wants to include, whatever data or things to assume>\n"
    # summary_instructions += "- Important context: <any other relevant context with the updated information explicitly mentioned>"
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
Summarize the current chat messages for:
'{user_message}'
Return ONLY the sections above, nothing else."""

    # Clone chatbot to avoid modifying the original
    chat = chatbot.clone(instructions_to_add=summary_instructions)
    
    MAX_TURNS = 8  # tiny safety to avoid infinite loops

    # 1) Ask LLM to extract from the initial message
    prompt = (
        "Task: Extract everything you can from the user's message into the schema. "
        "If the user is requesting changes to an existing JSON, locate the most recent JSON present "
        "anywhere in this conversation (assistant or user messages) and treat it as the authoritative "
        "baseline ('TRUTH'). Apply ONLY the requested changes, keeping all other fields intact. "
        "Do NOT ask questions about unchanged parts; ask ONLY if the requested change itself is ambiguous.\n\n"
        f"User message:\n{user_message}\n\n{_schema_instructions()}"
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
            "Do NOT include questions about anything present in the baseline JSON that the user did not ask to change.\n"
            + "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions))
            + "\n Respond in the same language as the user."
        )
        q_msg = chat.send_message(q_prompt)
        print(f"{chat.chat.__class__.__name__}: {q_msg}") # show LLM's question to the user
        # Save in to original chat history
        chatbot.mem.add_user(user_message)
        chatbot.mem.add_assistant(q_msg)

        user_answer = input("You: ").strip()
        if user_answer.lower() in {"exit", "quit"}:
            raise KeyboardInterrupt("User aborted.")

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
    
    # 3) Minimal shape checks (simple and strict)
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


# -------------------------------
# ----- Geoprocessing Logic -----
# -------------------------------

def geoprocess(json_instructions) -> str:
    #TODO: DUMMY FUNCTION
    return f"Here is the JSON instructions generated, assume this was processed: {json.dumps(json_instructions)}"

# ----------------
# ----- Main -----
# ----------------

def main(chatbot: Chatbot, msg: str) -> Optional[str]:
    print("Entered Geoprocessing Mode...")
    
    # Build JSON instructions via dialog
    json_instructions = complete_json(chatbot, msg)
    
    print("*"*60)
    print("Final JSON instructions:")
    print(json.dumps(json_instructions, ensure_ascii=False, indent=2))
    print("*"*60)
    # Save JSON generation in chat history
    chatbot.mem.add_assistant(f"Generated JSON instructions:\n{json.dumps(json_instructions, ensure_ascii=False, indent=2)}")

    msg_to_interpreter = geoprocess(json_instructions)
    
    return msg_to_interpreter
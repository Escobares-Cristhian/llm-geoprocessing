from typing import Optional, Tuple
from llm_geoprocessing.app.chatbot.chatbot import Chatbot
from llm_geoprocessing.app.plugins.preprocessing_plugin import get_metadata_preprocessing, get_documentation_preprocessing
from llm_geoprocessing.app.plugins.geoprocessing_plugin import get_metadata_geoprocessing, get_documentation_geoprocessing

from cli.chat_io import ChatIO

from llm_geoprocessing.app.logging_config import get_logger
logger = get_logger("geollm")

def _plugin_instructions() -> str:
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
        f"General Notes:\n"
        "- Do not assume availability of any data or capability that is not explicitly mentioned in 'Available Data and Preprocessing Options' or 'Geoprocessing Capabilities'."
        "- If a geoprocess is explicitly requested, and do not have the geoprocessing capabilities, then it is not a geospatial query and should be treated as a non-geospatial query, like a general knowledge question."
        "- If exits previous messages, and the user ask for a change or made a suggestion, then it is a geospatial query."
        "- Use activelly the previous messages to avoid asking for information that was already provided."
    )
    return plugin_instructions

def prepare_mode_prompt(modes: list, modes_explained: Optional[dict]=None) -> str:
    modes_str = "\n".join(f"- {mode}" for mode in modes)
    prompt = (
        "You are a mode selection agent. Please choose one of the following modes based on the user's input:\n"
        f"{modes_str}\n\n"
        "Respond with only the exact name of the selected mode."
    )
    if modes_explained:
        explanations = "\n".join(f"{mode}: {desc}" for mode, desc in modes_explained.items())
        prompt += f"\n\nMode Descriptions:\n{explanations}"
        prompt += "\n\nUse the descriptions to help you choose the most appropriate mode."
        prompt += "\n\nRemember to respond with only the exact name of the selected mode and nothing else."
    
    # Add plugin instructions for context
    prompt += f"\n\nContext Information Dump:\n{_plugin_instructions()}"
    
    # Add remainder of task
    prompt += "\n\nIMPORTANT: Do not confuse the algorithms explained in the Context Information Dump with the modes to select."
    prompt += "\n\nRemember to respond with only the exact name of one the following modes:"
    prompt += modes_str
    if modes_explained:
        explanations = "\n".join(f"{mode}: {desc}" for mode, desc in modes_explained.items())
        prompt += f"\n\nMode Descriptions:\n{explanations}"
        prompt += "\n\nUse the descriptions to help you choose the most appropriate mode."
        prompt += "\n\nRemember to respond with only the exact name of the selected mode and nothing else."
    
    return prompt


def define_mode(chatbot: Chatbot, msg: str, modes: list, modes_explained: Optional[dict]=None) -> str:
    def _match_mode(response: str, available_modes: list) -> Tuple[Optional[str], int]:
        count = 0
        selected_mode: Optional[str] = None
        for mode in available_modes:
            if mode.lower() == response.lower():
                return mode, 1
            if mode.lower() in response.lower():
                count += 1
                selected_mode = mode
        if count == 1 and selected_mode is not None:
            return selected_mode, count
        return None, count

    # Clone chatbot to avoid modifying the original
    chat = chatbot.clone(instructions_to_add=None)
    
    # Check for commands (only exit command is relevant here)
    command = chat.check_command(msg)
    if command == "exit":
        return "exit"

    # Prepare the mode selection prompt
    base_prompt = prepare_mode_prompt(modes, modes_explained)
    # Add user message to the prompt
    prompt = f"{base_prompt}\n\nUser Input: {msg}\n\nSelected Mode:"
    
    # --- Select mode
    # Ask for the mode once
    response = chat.chat_once(prompt).strip()
    selected_mode, count = _match_mode(response, modes)
    if selected_mode is not None:
        return selected_mode

    reason = "it did not match any allowed mode"
    if count > 1:
        reason = "it mentions multiple modes"

    retry_prompt = (
        f"{base_prompt}\n\n"
        f"User Input: {msg}\n\n"
        f"Your previous response was invalid because {reason}.\n"
        f"Previous response: {response}\n"
        "Please try again and respond with only one exact mode name.\n\n"
        "Selected Mode:"
    )
    retry_response = chat.chat_once(retry_prompt).strip()
    selected_mode, _ = _match_mode(retry_response, modes)
    if selected_mode is not None:
        return selected_mode
    
    # If no valid mode is selected, raise an error
    print(f"Mode selection failed. First response: {response}. Retry response: {retry_response}")
    raise ValueError("No valid mode selected.")


def define_mode_interaction(chatbot: Chatbot, chat_io: ChatIO, msg: str) -> str:
    modes = ["Geoproceso", "Consulta de Capacidades","Consulta o Interpretación de Datos", "Consulta no geoespacial"]

    modes_explained = {
        "Geoproceso": "Cuando el usuario pide o necesita realizar operaciones de geoprocesamiento como análisis espacial, manipulación de datos geográficos, generación de mapas, cálculo de estadísticas, etc. También cuando el usuario solicita cambios en geoprocesos previamente realizados.",
        "Consulta de Capacidades": "Cuando el usuario pregunta por las capacidades y/o datos disponibles. Ejemplos: '¿Qué puedes hacer?' ó '¿Qué datos tienes?'.",
        "Consulta o Interpretación de Datos": "Responder preguntas relacionadas con datos geográficos, interpretar información espacial, proporcionar explicaciones sobre conceptos geográficos, etc. Pero sin realizar operaciones de geoprocesamiento o cálculos.",
        "Consulta no geoespacial": "Responder preguntas generales que no estén relacionadas con datos geográficos o espaciales."
    }
    
    selected_mode = define_mode(chatbot, msg, modes, modes_explained)
    
    # If "Consulta de Capacidades", summarize the _plugin_instructions regarding user's message
    if selected_mode == "Consulta de Capacidades":
        summary_prompt = (
            "Summarize the available geoprocessing capabilities and data relevant to the user's message below, "
            "in a concise manner suitable for responding to the user's query about your capabilities and data.\n\n"
            "Dump of Geoprocessing and Data Capabilities (both metadata and documentation for each):\n"
            f"{_plugin_instructions()}\n\n"
            f"User Message: {msg}\n\n"
            "Summary:"
        )
        summary = chatbot.clone().send_message(summary_prompt)
        chat_io.print_assistant_msg(summary) # show LLM's question to the user
    
    mode_to_workflow = {
        "exit": "exit",
        "Geoproceso": "geoprocessing",
        "Consulta de Capacidades": "ask for input",
        "Consulta o Interpretación de Datos": "interpreter",
        "Consulta no geoespacial": "interpreter"
    }
    
    selected_mode = mode_to_workflow[selected_mode]
    
    return selected_mode

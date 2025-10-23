from typing import Optional
from llm_geoprocessing.app.chatbot.chatbot import Chatbot
from llm_geoprocessing.app.plugins.preprocessing_plugin import get_metadata_preprocessing, get_documentation_preprocessing
from llm_geoprocessing.app.plugins.geoprocessing_plugin import get_metadata_geoprocessing, get_documentation_geoprocessing

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
    
    return prompt


def define_mode(msg: str, modes: list, modes_explained: Optional[dict]=None) -> str:
    # Initialize chatbot
    chatbot = Chatbot()
    
    # Check for commands (only exit command is relevant here)
    command = chatbot.check_command(msg)
    if command == "exit":
        return "exit"

    # Prepare the mode selection prompt
    prompt = prepare_mode_prompt(modes, modes_explained)
    # Add user message to the prompt
    prompt += f"\n\nUser Input: {msg}\n\nSelected Mode:"
    
    # --- Select mode
    # Ask for the mode once
    response = chatbot.chat_once(prompt)

    # Check if the response matches one of the modes
    if response in modes:
        return response

    # Check if only one mode is present in the response
    count = 0
    selected_mode = None
    for mode in modes:
        if mode in response:
            count += 1
            selected_mode = mode

    if count == 1:
        return selected_mode
    
    # If no valid mode is selected, raise an error
    raise ValueError("No valid mode selected.")


def define_mode_interaction(msg) -> str:
    modes = ["Geoproceso", "Consulta o Interpretación de Datos", "Consulta no geoespacial"]

    modes_explained = {
        "Geoproceso": "Cuando el usuario pide o necesita realizar operaciones de geoprocesamiento como análisis espacial, manipulación de datos geográficos, generación de mapas, cálculo de estadísticas, etc.",
        "Consulta o Interpretación de Datos": "Responder preguntas relacionadas con datos geográficos, interpretar información espacial, proporcionar explicaciones sobre conceptos geográficos, etc. Pero sin realizar operaciones de geoprocesamiento o cálculos.",
        "Consulta no geoespacial": "Responder preguntas generales que no estén relacionadas con datos geográficos o espaciales."
    }
    
    selected_mode = define_mode(msg, modes, modes_explained)
    
    mode_to_workflow = {
        "exit": "exit",
        "Geoproceso": "geoprocessing",
        "Consulta o Interpretación de Datos": "interpreter",
        "Consulta no geoespacial": "interpreter"
    }
    
    selected_mode = mode_to_workflow[selected_mode]
    
    return selected_mode
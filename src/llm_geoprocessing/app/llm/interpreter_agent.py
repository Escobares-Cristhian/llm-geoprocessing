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
        "- If a geoprocess is requested, and do not have all required data or geoprocessing capabilities, list precise questions in 'questions'.\n"
        "- Do not assume availability of any data or capability that is not explicitly mentioned in 'Available Data and Preprocessing Options' or 'Geoprocessing Capabilities'.\n"
    )
    return plugin_instructions

def main(chatbot: Chatbot, msg_from_geoprocess: Optional[str], msg_from_user: str) -> Chatbot | str:
    print("Entered Interpreter Mode...")
    chat = chatbot.clone(instructions_to_add=None)
    
    # Prepare interpreter prompt
    interpreter_prompt = "Respond this message from User:"
    if msg_from_geoprocess is not None:
        interpreter_prompt += f"\nOutput Information from Geoprocessing Mode:\n{msg_from_geoprocess}\n"
        interpreter_prompt += "\n\nAdditional Context Information Dump:\n"
        interpreter_prompt += _plugin_instructions()
        
        # DEBUG: Add assume instructions were generated and invent the output response
        interpreter_prompt += "Assume the above instructions were processed and generated correctly, invent the output to give a dummy (but plausible) response to the user message.\n"
    
    # -----------------------------------------------------------------
    # ----- TODO: MISSING WAY TO GET INFORMATION FROM THE GEODATA -----
    # -----------------------------------------------------------------
    
    interpreter_prompt += f"\nUser Message:\n{msg_from_user}\n"
    interpreter_prompt += (
        "\nBased on the above information, please provide a suitable response to the user's message."
        " Be concise and relevant. Do not mention the JSON Instructions or Geoprocessing Mode."
        " Respond in the same language as the user's message."
    )
    
    # Check for commands (only exit command is relevant here)
    command = chat.check_command(interpreter_prompt)
    if command == "exit":
        return "exit"
    
    # Send message to LLM and get response||
    response = chat.send_message(interpreter_prompt)
    print(f"{chatbot.chat.__class__.__name__}: {response}") # show LLM's question to the user
    
    # Save assistant response in to original chat history
    chatbot.mem.add_assistant(response)
    
    return chatbot

    
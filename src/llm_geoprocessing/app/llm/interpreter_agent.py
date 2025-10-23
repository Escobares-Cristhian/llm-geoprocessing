from typing import Optional
from llm_geoprocessing.app.chatbot.chatbot import Chatbot

def main(chatbot: Chatbot, msg_from_geoprocess: Optional[str], msg_from_user: str) -> Chatbot | str:
    print("Entered Interpreter Mode...")
    
    # Prepare interpreter prompt
    interpreter_prompt = "Respond this message from User:"
    if msg_from_geoprocess is not None:
        interpreter_prompt += f"\nOutput Information from Geoprocessing Mode:\n{msg_from_geoprocess}\n"
    
    # -----------------------------------------------------------------
    # ----- TODO: MISSING WAY TO GET INFORMATION FROM THE GEODATA -----
    # -----------------------------------------------------------------
    
    interpreter_prompt += f"\nUser Message:\n{msg_from_user}\n"
    interpreter_prompt += (
        "\nBased on the above information, please provide a suitable response to the user's message."
        " Be concise and relevant."
    )
    
    # Check for commands (only exit command is relevant here)
    command = chatbot.check_command(interpreter_prompt)
    if command == "exit":
        return "exit"
    
    # Send message to LLM and get response||
    response = chatbot.send_message(interpreter_prompt)
    print(f"{chatbot.chat.__class__.__name__}: {response}") # show LLM's question to the user
    
    return chatbot

    
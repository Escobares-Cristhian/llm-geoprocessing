from llm_geoprocessing.app.chatbot.chatbot import Chatbot
from llm_geoprocessing.app.llm.mode_selector_agent import define_mode_interaction
from llm_geoprocessing.app.llm.geoprocess_agent import main as geoprocess_main
from llm_geoprocessing.app.llm.interpreter_agent import main as interpreter_main

def get_user_input(chat_prefix: str = "You: ") -> str:
    msg = ""
    while not msg.strip():
        msg = input(chat_prefix)
    return msg

if __name__ == "__main__":
    # Initialize chatbot
    chatbot = Chatbot()
    
    # --------------------------------------
    # ----- Mode Selection Interaction -----
    # --------------------------------------
    
    # Start chat until not empty input is given
    msg = get_user_input()
    
    # Select mode based on user input
    selected_mode = define_mode_interaction(msg)
    
    # Handle exit command
    if selected_mode == "exit":
        exit()
    
    # Print selected mode
    print(f"[Selected Mode: {selected_mode}]")
    
    # Check if it is geoprocessing mode or interpreter mode
    if selected_mode not in ["geoprocessing", "interpreter"]:
        raise ValueError(f"Invalid mode selected: {selected_mode}")
    
    
    # -------------------------------------
    # ----- Geoprocessing Interaction -----
    # -------------------------------------
    
    if selected_mode == "geoprocessing":
        print("Entering Geoprocessing Mode...")
        geoprocess_main()
    
    # -----------------------------------
    # ----- Interpreter Interaction -----
    # -----------------------------------
    print("Entering Interpreter Mode...")
    interpreter_main()
    
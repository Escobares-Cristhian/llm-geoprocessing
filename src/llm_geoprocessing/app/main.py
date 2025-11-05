from llm_geoprocessing.app.chatbot.chatbot import Chatbot
from llm_geoprocessing.app.llm.mode_selector_agent import define_mode_interaction
from llm_geoprocessing.app.llm.geoprocess_agent import main as geoprocess_main
from llm_geoprocessing.app.llm.interpreter_agent import main as interpreter_main

def get_user_input(chatbot: Chatbot, chat_prefix: str = "You: ") -> str | None:
    valid_user_msg = False
    while not valid_user_msg:
        msg = input(chat_prefix).strip()

        # Check for commands
        command = chatbot.check_command(msg)
        if command == "exit":
            return "exit"
        elif command == "ask for input":
            continue  # ask again
        elif command:
            print(command) # print command output and ask again
            continue

        valid_user_msg = True
    
    return msg

if __name__ == "__main__":
    # Initialize chatbot
    chatbot = Chatbot()
    
    while True:
        # --------------------------------------
        # ----- Mode Selection Interaction -----
        # --------------------------------------
        
        # Start chat until not empty input is given
        msg = get_user_input(chatbot)
        
        # Handle exit command
        if msg == "exit":
            exit()
        
        # Select mode based on user input
        selected_mode = define_mode_interaction(chatbot, msg)
        
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
        
        msg_to_interpreter = None
        if selected_mode == "geoprocessing":
            print("Entering Geoprocessing Mode...")
            msg_to_interpreter = geoprocess_main(chatbot, msg)
            
            # Handle exit command
            if msg_to_interpreter == "exit":
                exit()
        
        # -----------------------------------
        # ----- Interpreter Interaction -----
        # -----------------------------------
        print("Entering Interpreter Mode...")
        chatbot = interpreter_main(chatbot, msg_to_interpreter, msg)
        
        # Handle exit command
        if chatbot == "exit":
            exit()
    
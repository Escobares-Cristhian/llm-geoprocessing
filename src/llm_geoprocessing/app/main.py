from llm_geoprocessing.app.chatbot.chatbot import Chatbot
from llm_geoprocessing.app.llm.mode_selector_agent import define_mode_interaction


if __name__ == "__main__":
    # Initialize chatbot
    chatbot = Chatbot()
    
    # # Select mode based on user input
    # selected_mode = define_mode_interaction()
    # print(f"Selected Mode: {selected_mode}")
    
    while True:
        msg = input("You: ")
        
        # If empty input, ask again for input
        if not msg.strip():
            continue
        
        # Select mode based on user input
        selected_mode = define_mode_interaction(msg)

        # Handle exit command
        if selected_mode == "exit":
            break
        
        # Print selected mode
        print(f"Selected Mode: {selected_mode}")
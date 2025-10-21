import os
from typing import Optional
from llm_geoprocessing.app.llm.LLM import Gemini, ChatMemory


class Chatbot:
    def __init__(self):
        # Gemini
        self.chat = Gemini(model="gemini-2.5-flash", quiet=True)
        self.chat.config_api()
        self.mem = ChatMemory()
    
    def check_command(self, msg: str) -> Optional[str]:
        low = msg.strip().lower()
        if low in ["exit", "quit"]:
            return "exit"
        if low in [":history", "/history"]:
            return self.mem.as_string(self.chat.__class__.__name__)
        if low in [":clear", "/clear"]:
            self.mem.clear()
            return "[memory cleared]"
        return None

    def send_message(self, msg: str) -> str:
        self.mem.add_user(msg)
        response = self.chat.send_msg(self.mem.messages(), quiet=True)
        self.mem.add_assistant(response)
        return response
    
    def chat_once(self, msg: Optional[str] = None):
        # If no message provided, ask for input
        if msg is None:
            msg = input("You: ")
        
        # If empty input, ask again for input
        if not msg.strip():
            return "ask for input"
        
        # Check for commands
        command = self.check_command(msg)
        if command == "exit":
            return "exit"
        if command:
            return command

        # Send message to LLM and get response
        response = self.send_message(msg)
        return response
    
    def interactive_chat(self):
        while True:
            response = self.chat_once()
            
            # If empty input, ask again for input
            if response == "ask for input":
                continue
            
            # Handle exit command
            if response == "exit":
                break
            
            # Print LLM response
            print(f"{self.chat.__class__.__name__}:", response)

if __name__ == "__main__":
    # Initialize chatbot
    chatbot = Chatbot()

    # Start interactive chat
    chatbot.interactive_chat()

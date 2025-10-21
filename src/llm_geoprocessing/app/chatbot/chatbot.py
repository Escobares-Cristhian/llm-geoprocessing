import os
from llm_geoprocessing.app.llm.LLM import Gemini, ChatMemory


class Chatbot:
    def __init__(self):
        # Gemini
        self.chat = Gemini(model="gemini-2.5-flash", quiet=True)
        self.chat.config_api()
        self.mem = ChatMemory()
    
    def check_command(self, msg):
        low = msg.strip().lower()
        if low in ["exit", "quit"]:
            return "exit"
        if low in [":history", "/history"]:
            return self.mem.as_string(self.chat.__class__.__name__)
        if low in [":clear", "/clear"]:
            self.mem.clear()
            return "[memory cleared]"
        return None
    
    def send_message(self, msg):
        self.mem.add_user(msg)
        response = self.chat.send_msg(self.mem.messages(), quiet=True)
        self.mem.add_assistant(response)
        return response
    
    def interactive_chat(self):
        while True:
            msg = input("You: ")
            if not msg.strip():
                continue

            command = self.check_command(msg)
            if command == "exit":
                break
            if command:
                print(command)
                continue

            response = self.send_message(msg)
            print(f"{self.chat.__class__.__name__}:", response)
    

if __name__ == "__main__":
    # Initialize chatbot
    chatbot = Chatbot()

    # Start interactive chat
    chatbot.interactive_chat()

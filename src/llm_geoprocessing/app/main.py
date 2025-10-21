from llm_geoprocessing.app.chatbot.chatbot import Chatbot

if __name__ == "__main__":
    # Initialize chatbot
    chatbot = Chatbot()

    # Start interactive chat
    chatbot.interactive_chat()
    
    # Test single chat once
    response = chatbot.chat_once()
    print(f"{chatbot.chat.__class__.__name__}:", response)
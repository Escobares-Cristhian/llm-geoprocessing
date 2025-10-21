import os
from llm_geoprocessing.app.llm.LLM import Gemini, ChatMemory

if __name__ == "__main__":
    # Gemini
    chat = Gemini(model="gemini-2.5-flash", quiet=True)
    chat.config_api()
        
    # Clear the console
    os.system('clear')

    mem = ChatMemory()
    
    # Interactive chat
    while True:
        msg = input("You: ")
        if not msg.strip():
            continue
        low = msg.strip().lower()
        if low in ["exit", "quit"]:
            break
        if low in [":history", "/history"]:
            print(mem.as_string(chat.__class__.__name__))
            continue
        if low in [":clear", "/clear"]:
            mem.clear()
            print("[memory cleared]")
            continue

        mem.add_user(msg)
        response = chat.send_msg(mem.messages(), quiet=True)
        mem.add_assistant(response)
        print(f"{chat.__class__.__name__}:", response)

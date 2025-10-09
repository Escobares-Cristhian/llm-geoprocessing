import os
from llm_geoprocessing.app.llm.LLM import Gemini

if __name__ == "__main__":
    # Gemini
    g = Gemini(model="gemini-2.5-flash")
    g.config_api()
    # print("Gemini:", g.send_msg("Say hi in 5 words."))
    
    # Clear the console
    os.system('clear')

    
    # Interactive chat
    while True:
        msg = input("You: ")
        if msg.lower() in ["exit", "quit"]:
            break
        response = g.send_msg(msg, quiet=True)
        print("Gemini:", response)
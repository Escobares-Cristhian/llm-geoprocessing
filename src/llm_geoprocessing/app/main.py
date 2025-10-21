from llm_geoprocessing.app.chatbot.chatbot import Chatbot
from llm_geoprocessing.app.llm.mode_selector_agent import define_mode

def define_mode_interaction() -> str:
    msg = input("You: ")
    
    modes = ["Geoproceso", "Consulta o Interpretación de Datos", "Consulta no geoespacial"]

    modes_explained = {
        "Geoproceso": "Realizar operaciones de geoprocesamiento como análisis espacial, manipulación de datos geográficos, generación de mapas, etc.",
        "Consulta o Interpretación de Datos": "Responder preguntas relacionadas con datos geográficos, interpretar información espacial, proporcionar explicaciones sobre conceptos geográficos, etc.",
        "Consulta no geoespacial": "Responder preguntas generales que no estén relacionadas con datos geográficos o espaciales."
    }
    
    selected_mode = define_mode(msg, modes, modes_explained)
    
    return selected_mode

if __name__ == "__main__":
    # Initialize chatbot
    chatbot = Chatbot()
    
    # # Select mode based on user input
    # selected_mode = define_mode_interaction()
    # print(f"Selected Mode: {selected_mode}")
    
    while True:
        # Select mode based on user input
        selected_mode = define_mode_interaction()
        print(f"Selected Mode: {selected_mode}")
        
        # Handle exit command
        if selected_mode == "exit":
            break
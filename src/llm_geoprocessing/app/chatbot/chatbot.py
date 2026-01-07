import os
from typing import Optional
# from llm_geoprocessing.app.llm.LLM import ChatGPT, Ollama, Gemini, ChatMemory
from llm_geoprocessing.app.llm.LLM import FactoryLLM, ChatMemory
from llm_geoprocessing.app.chatdb import get_chatdb
from llm_geoprocessing.app.chatdb.context import set_session_id

from llm_geoprocessing.app.logging_config import get_logger
logger = get_logger("geollm")

class Chatbot:
    def __init__(self, persist: bool = True):
        
        # Select + configure LLM from Factory
        self.chat = FactoryLLM.create_llm(quiet=True)
        
        self.chatdb = None
        self.session_id = None
        if persist:
            self.chatdb = get_chatdb()
            if self.chatdb.enabled:
                self.chatdb.ensure_schema()
                self.session_id = self.chatdb.create_session()
                set_session_id(self.session_id)
                self.mem = ChatMemory(chatdb=self.chatdb, session_id=self.session_id, persist=True)
            else:
                self.mem = ChatMemory(persist=False)
        else:
            self.mem = ChatMemory(persist=False)
        
        # Add general information to system
        self.mem.add_system(self._add_system_info())
    
    def _add_system_info(self):
        system_info = "Today's date is " + os.popen(
            "date '+YYYY-MM-DD = %Y-%m-%d at HH:MM:SS = %H:%M:%S'"
            ).read().strip() + ".\n"
        return system_info
    
    def check_command(self, msg: str) -> Optional[str]:
        low = msg.strip().lower()
        if low in ["exit", "quit"]:
            return "exit"
        if low in [":history", "/history"]:
            history =  self.mem.as_string(self.chat.__class__.__name__, include_system=False)
            return "----- INIT: Chat History -----\n" + history + "\n----- END: Chat History -----"
        if low in [":history-with-system", "/history-with-system"]:
            history =  self.mem.as_string(self.chat.__class__.__name__, include_system=True)
            return "----- INIT: Chat History (with system) -----\n" + history + "\n----- END: Chat History -----"
        if low in [":clear", "/clear"]:
            self.mem.clear()
            return "[memory cleared]"
        return None
    
    def clone(self, instructions_to_add: Optional[str] = None):
        """Create a clone of the chatbot with independent memory copy."""
        cloned = Chatbot(persist=False)

        # *** share the same LLM client so RPM limit is global across clones ***
        cloned.chat = self.chat

        # fresh memory for the clone
        cloned.mem = ChatMemory(persist=False)
        cloned.mem.load_messages(self.mem.messages())
        
        if instructions_to_add is None:
            return cloned
        
        # Extract instructions from memory with a chat call
        resumen = cloned.send_message(instructions_to_add)
        
        logger.debug("*"*60)
        logger.debug("Resumen para nuevo chatbot clonado:")
        logger.debug(resumen)
        logger.debug("*"*60)

        # Elimino memoria
        cloned.mem.clear()
        
        # Add general information to system
        cloned.mem.add_system(cloned._add_system_info())
        
        # Agrego resumen a la memoria
        cloned.mem.add_system(resumen)
        # cloned.mem.add_user(resumen)
        
        return cloned

    def send_message(self, msg: str) -> str:
        self.mem.add_user(msg)
        response = self.chat.send_msg(self.mem.messages(), quiet=True)
        self.mem.add_assistant(response)
        return response
    
    def chat_once(self, msg: Optional[str] = None):
        # If no message provided, ask for input
        if msg is None:
            return "ask for input"
        
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
        return f"{self.chat.__class__.__name__}: {response}"

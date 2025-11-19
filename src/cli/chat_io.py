import sys

class ChatIO:
    def __init__(self, user_name: str, model_name: str) -> None:
        self.user_name = user_name
        self.model_name = model_name

    def ask_user_input(self) -> str | None:
        return input(f"\n{self.user_name}: ")

    def print_user_msg(self, msg: str) -> None:
        out_print = f"\n{self.user_name}:\n{msg}"
        print(out_print, flush=True, sep='')

    def print_assistant_msg(self, msg: str) -> None:
        out_print = f"\n{self.model_name}:\n{msg}"
        print(out_print, flush=True, sep='')

    def print_command_msg(self, command_name: str, msg: str) -> None:
        out_print = f"\n[{command_name}]:\n{msg}"
        print(out_print, flush=True, sep='')

    def print_mode_selected(self, mode_name: str) -> None:
        out_print = f"\n[Selected Mode: {mode_name}]"
        print(out_print, flush=True, sep='')

import sys

def ask_user_input(chat_prefix:str) -> str | None:
    return input(chat_prefix)

def print_user_msg(user_name: str, msg: str) -> None:
    out_print = f"\n{user_name}:\n{msg}"
    print(out_print, flush=True, sep='')

def print_assistant_msg(model_name: str, msg: str) -> None:
    out_print = f"\n{model_name}:\n{msg}"
    print(out_print, flush=True, sep='')

def print_command_msg(command_name: str, msg: str) -> None:
    out_print = f"\n[{command_name}]:\n{msg}"
    print(out_print, flush=True, sep='')

def print_mode_selected(mode_name: str) -> None:
    out_print = f"\n[Selected Mode: {mode_name}]"
    print(out_print, flush=True, sep='')
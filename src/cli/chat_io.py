# src/cli/chat_io.py

class ChatIO:
    def __init__(
        self,
        user_name: str = "User",
        model_name: str = "Assistant",
        use_gui: bool = True,
        window_title: str = "GeoLLM Chat",
    ) -> None:
        self.user_name = user_name
        self.model_name = model_name
        self.use_gui = use_gui

        self._pending_input: str | None = None
        self._root = None
        self._text = None
        self._entry = None
        self._tk = None

        if self.use_gui:
            # No fallback: if this fails, let it raise
            import tkinter as tk

            self._tk = tk
            self._root = tk.Tk()
            self._root.title(window_title)

            self._text = tk.Text(self._root, state="disabled", wrap="word")
            self._text.pack(fill="both", expand=True)

            self._entry = tk.Entry(self._root)
            self._entry.pack(fill="x")
            self._entry.bind("<Return>", self._on_send)

            send_button = tk.Button(self._root, text="Send", command=self._on_send)
            send_button.pack()

    def ask_user_input(self) -> str | None:
        if not self.use_gui:
            return input(f"\n{self.user_name}: ")

        # Update GUI before waiting for input
        self._pending_input = None
        while self._pending_input is None:
            self._root.update()

        msg = self._pending_input
        self._pending_input = None
        
        # Show the user message in the GUI
        self.print_user_msg(msg)
        
        # Update GUI after getting input
        self._root.update()
    
        return msg

    def print_user_msg(self, msg: str) -> None:
        self._append(f"\n{self.user_name}:\n{msg}")

    def print_assistant_msg(self, msg: str) -> None:
        self._append(f"\n{self.model_name}:\n{msg}")

    def print_command_msg(self, command_name: str, msg: str) -> None:
        self._append(f"\n[{command_name}]:\n{msg}")

    def print_mode_selected(self, mode_name: str) -> None:
        self._append(f"\n[Selected Mode: {mode_name}]")

    # ----- internal helpers -----

    def _append(self, text: str) -> None:
        if not self.use_gui or self._text is None:
            print(text, flush=True, sep="")
            return

        self._text.configure(state="normal")
        self._text.insert("end", text + "\n")
        self._text.configure(state="disabled")
        self._text.see("end")

    def _on_send(self, event=None) -> None:  # type: ignore[override]
        if self._entry is None:
            return
        msg = self._entry.get()
        if not msg:
            return
        self._entry.delete(0, "end")
        self._pending_input = msg

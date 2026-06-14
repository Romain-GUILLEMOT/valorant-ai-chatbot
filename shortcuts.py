import keyboard
import ollama_client

HOTKEYS = {
    "force_new_game": "t+n",
    "ally_score_up": "t+up",
    "ally_score_down": "t+down",
    "enemy_score_up": "t+right",
    "enemy_score_down": "t+left"
}

def start_shortcuts(on_force_new_game, on_score_delta, on_ai_prompt):
    keyboard.add_hotkey(HOTKEYS["force_new_game"], on_force_new_game)
    keyboard.add_hotkey(HOTKEYS["ally_score_up"], lambda: on_score_delta("allies", 1))
    keyboard.add_hotkey(HOTKEYS["ally_score_down"], lambda: on_score_delta("allies", -1))
    keyboard.add_hotkey(HOTKEYS["enemy_score_up"], lambda: on_score_delta("enemies", 1))
    keyboard.add_hotkey(HOTKEYS["enemy_score_down"], lambda: on_score_delta("enemies", -1))
    for prompt_id, prompt in ollama_client.PROMPTS.items():
        keyboard.add_hotkey(prompt["hotkey"], lambda pid=prompt_id: on_ai_prompt(pid))

    print(f"[+] shortcut loaded: {HOTKEYS['force_new_game']} => nouvelle partie + full scan")
    print("[+] score shortcuts: T+Up/Down allies, T+Right/Left enemies")
    print("[+] ai shortcuts: T+U/I/O/P/J prompts, T+K disclaimer")
    keyboard.wait()

import keyboard

HOTKEYS = {
    "force_new_game": "t+n",
    "ally_score_up": "t+up",
    "ally_score_down": "t+down",
    "enemy_score_up": "t+right",
    "enemy_score_down": "t+left"
}

def start_shortcuts(on_force_new_game, on_score_delta):
    keyboard.add_hotkey(HOTKEYS["force_new_game"], on_force_new_game)
    keyboard.add_hotkey(HOTKEYS["ally_score_up"], lambda: on_score_delta("allies", 1))
    keyboard.add_hotkey(HOTKEYS["ally_score_down"], lambda: on_score_delta("allies", -1))
    keyboard.add_hotkey(HOTKEYS["enemy_score_up"], lambda: on_score_delta("enemies", 1))
    keyboard.add_hotkey(HOTKEYS["enemy_score_down"], lambda: on_score_delta("enemies", -1))
    print(f"[+] shortcut loaded: {HOTKEYS['force_new_game']} => nouvelle partie + full scan")
    print("[+] score shortcuts: T+Up/Down allies, T+Right/Left enemies")
    keyboard.wait()

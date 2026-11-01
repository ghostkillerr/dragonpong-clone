"""Run the source-only DragonPong-inspired offline prototype."""

from __future__ import annotations

import json
import os
import queue
import time
from pathlib import Path
from dragonpong import native_ui as ui

from dragonpong.audio import AudioOutput
from dragonpong.client import Connection, PaddlePrediction
from dragonpong.engine import Bot, COURT_LENGTH, Event, HALF_WIDTH, Match, Rules
from dragonpong.controls import ControllerInput
from dragonpong.netplay import MAX_CONTACT_LAG, present_flight, view_is_stale, view_seconds

CHARACTERS = ['Lord owny', 'Uncle Sam', 'Evil Sammy', 'David The Eighth', 'Karakter 5']

PROFILE = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "DragonPongClone" / "profile.json"
if os.environ.get('DRAGONPONG_PROFILE'):
    PROFILE = Path(os.environ['DRAGONPONG_PROFILE'])


def load_profile() -> dict:
    defaults = {"name": "Oyuncu", "score": 10, "shield": True,
                "silent_ball": True, "difficulty": "Orta"}
    try:
        data = json.loads(PROFILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            if isinstance(data.get('name'), str) and 1 <= len(data['name'].strip()) <= 24:
                defaults['name'] = data['name'].strip()
            if type(data.get('score')) is int and 1 <= data['score'] <= 2147483647:
                defaults['score'] = data['score']
            for key in ('shield', 'silent_ball'):
                if type(data.get(key)) is bool:
                    defaults[key] = data[key]
            if data.get('difficulty') in Bot.LEVELS:
                defaults['difficulty'] = data['difficulty']
    except (OSError, ValueError):
        pass
    return defaults


class Game:
    def __init__(self) -> None:
        self.root = ui.Window()
        self.closing = False
        self.tick_in_progress = False
        self.root.title("DragonPong Kaynak Klon")
        self.root.geometry("620x710")
        self.root.minsize(500, 600)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.audio = AudioOutput()
        self.controller = ControllerInput()
        self.audio_error = ""
        try:
            self.audio.start()
        except Exception as exc:
            self.audio_error = f"Ses aygıtı açılamadı: {exc}"
        self.match: Match | None = None
        self.bot: Bot | None = None
        self.connection: Connection | None = None
        self.paddle_prediction = PaddlePrediction()
        self.online_state: dict | None = None
        self.presented_view: dict | None = None
        self.network_notice_active = False
        self.network_recovery_since = None
        self.online_player: int | None = None
        self.online_rooms: list[dict] = []
        self.browsing_spectator = False
        self.last_direction = 0
        self.pressed: set[str] = set()
        self.last_tick = time.perf_counter()
        self.profile = load_profile()
        self.characters = [0, 1]
        self.container = ui.Panel(self.root, padding=18)
        self.container.pack(fill="both", expand=True)
        self.menu()
        self.root.bind_all("<KeyPress>", self.key_down)
        self.root.bind_all("<KeyRelease>", self.key_up)
        self.root.after(16, self.tick)

    def clear(self) -> None:
        self.root.desired_focus = None
        self.root.clear_announcement()
        for child in self.container.winfo_children():
            child.destroy()
        self.network_label = None
        if self.connection:
            self.network_label = ui.Label(self.container, text='Sunucuya bağlanılıyor...', wraplength=550)
            self.network_label.pack(side='bottom', anchor='w', pady=5)
        self.root.after_idle(self.bind_navigation)

    def send_online(self, kind: str, **fields) -> bool:
        if not self.connection:
            return False
        try:
            self.connection.send(kind, **fields)
            return True
        except OSError as exc:
            self.online_message({'type': 'connection_error', 'reason': str(exc)})
            return False

    def network_stalled(self) -> bool:
        state = self.online_state
        limit = MAX_CONTACT_LAG if getattr(self.connection, 'supports_strike_ref', False) is True else 1
        return bool(state and state.get('winner') is None and
                    isinstance(state.get('_received_at'), (float, int)) and
                    view_is_stale(state, time.monotonic(), limit))

    def network_text(self) -> str:
        if not self.connection:
            return 'Bağlantı kapalı'
        text = self.connection.status_text()
        if self.network_stalled():
            text += ' | Oyun verisi gecikiyor'
        return text

    def update_network_notice(self) -> None:
        if not self.connection or not self.online_state or self.online_state.get('winner') is not None:
            self.network_notice_active = False
            self.network_recovery_since = None
            return
        now = time.monotonic()
        if self.network_stalled():
            self.network_recovery_since = None
            if not self.network_notice_active:
                self.network_notice_active = True
                self.announce('Oyun verisi gecikiyor. Yeni girişler bekletiliyor.')
        elif self.network_notice_active:
            if self.network_recovery_since is None:
                self.network_recovery_since = now
            elif now - self.network_recovery_since >= .25:
                self.network_notice_active = False
                self.network_recovery_since = None
                self.announce('Bağlantı düzeldi. Oyun sürüyor.')

    def save_profile(self) -> None:
        PROFILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = PROFILE.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.profile, ensure_ascii=False), encoding='utf-8')
        temporary.replace(PROFILE)

    def bind_navigation(self) -> None:
        widgets = [w for w in self.container.winfo_children()
                   if w.winfo_class() in ('Button', 'CheckBox', 'Entry', 'ComboBox', 'ListBox')]
        for index, widget in enumerate(widgets):
            if widget.winfo_class() in ('Button', 'CheckBox', 'Entry'):
                for key, delta in (('<Up>', -1), ('<Down>', 1)):
                    def move(_event, i=index, d=delta):
                        widgets[(i + d) % len(widgets)].focus_set()
                        return 'break'
                    widget.bind(key, move)
            if widget.winfo_class() in ('Button', 'CheckBox'):
                widget.bind('<Return>', lambda event: (event.widget.invoke(), 'break')[1])
        if widgets and self.root.desired_focus is None:
            widgets[0].focus_set()

    def title_message(self, text: str) -> None:
        self.root.announce(text)

    def install_mouse_controls(self) -> None:
        self.mouse_wheel_steps = 0
        self.canvas.bind('<Button-1>', lambda _event: self.key_down(type('Key', (), {'keysym': 'Up'})()))
        self.canvas.bind('<MouseWheel>', self.mouse_wheel)

    def mouse_wheel(self, event) -> None:
        self.mouse_wheel_steps += int(event.delta / 120)
        if abs(self.mouse_wheel_steps) >= 3:
            key = 'Right' if self.mouse_wheel_steps > 0 else 'Left'
            self.mouse_wheel_steps = 0
            self.key_down(type('Key', (), {'keysym': key})())

    def remember_name(self, _event=None) -> None:
        if not self.name.winfo_exists():
            return
        value = self.name.get().strip()
        if 1 <= len(value) <= 24:
            self.profile['name'] = value
            self.save_profile()

    def remember_settings(self, _event=None) -> None:
        try:
            rules = Rules(int(self.score.get()), self.shield.get(), self.silent.get())
        except (ValueError, TypeError, ui.UIError):
            return
        self.profile.update(score=rules.score, shield=rules.shield, silent_ball=rules.silent_ball)
        if hasattr(self, 'difficulty') and self.difficulty.winfo_exists():
            if self.difficulty.get() in Bot.LEVELS:
                self.profile['difficulty'] = self.difficulty.get()
        self.save_profile()

    def menu(self) -> None:
        if self.connection:
            self.connection.close()
            self.connection = None
        self.match = None
        self.online_state = None
        self.presented_view = None
        self.network_notice_active = False
        self.network_recovery_since = None
        self.online_player = None
        self.paddle_prediction.reset()
        self.pressed.clear()
        self.last_direction = 0
        self.audio.listener = 0
        self.audio.listener_x = 0
        self.audio.reset()
        self.audio.music('Music/Menu.wav')
        self.clear()
        self.root.title("DragonPong Kaynak Klon - Ana menü")
        ui.Label(self.container, text="DragonPong kaynak klon", font=("Segoe UI", 17)).pack(anchor="w", pady=12)
        ui.Label(self.container, text="Adın").pack(anchor="w")
        self.name = ui.Entry(self.container, name="Adın")
        self.name.insert(0, str(self.profile["name"]))
        self.name.pack(fill="x", pady=5)
        self.name.bind('<FocusOut>', self.remember_name)
        ui.Button(self.container, text="Bota karşı oyna", command=self.offline_character_menu).pack(fill="x", pady=15)
        ui.Button(self.container, text="Oyuncu olarak bağlan", command=lambda: self.online_menu(False)).pack(fill="x", pady=5)
        ui.Button(self.container, text="İzleyici olarak bağlan", command=lambda: self.online_menu(True)).pack(fill="x", pady=5)
        self.error = ui.Label(self.container, text=self.audio_error, foreground="#a22")
        self.error.pack(anchor="w")
        ui.Button(self.container, text="Çık", command=self.close).pack(fill="x", pady=5)
        ui.Label(self.container, text="Sol/sağ ok veya A/D: bir adım. Yukarı ok veya boşluk: servis ve vuruş. Escape: ana menü.",
                  wraplength=540).pack(anchor="w", pady=12)
        self.name.focus_set()

    def offline_character_menu(self) -> None:
        name = self.name.get().strip()
        if not 1 <= len(name) <= 24:
            self.error.config(text="Ad 1 ile 24 karakter arasında olmalı.")
            return
        self.profile["name"] = name
        self.save_profile()
        self.root.title('DragonPong - Karakter seçimi')
        self.clear()
        ui.Label(self.container, text="Karakterini seç", font=("Segoe UI", 16)).pack(anchor="w", pady=12)
        self.character = ui.ComboBox(self.container, values=CHARACTERS, name="Karakter",
                                       state="readonly")
        self.character.current(0)
        self.character.bind('<<ComboboxSelected>>', self.character_sound)
        self.audio.music('Music/charselect.wav')
        self.character.pack(fill="x", pady=8)
        ui.Button(self.container, text="Seçimi onayla", command=self.offline_settings).pack(fill="x")
        self.character.focus_set()

    def offline_settings(self) -> None:
        self.root.title('DragonPong - Maç ayarları')
        self.characters = [self.character.current(), (self.character.current() + 1) % 5]
        self.audio.music(None)
        self.clear()
        ui.Label(self.container, text="Maç ayarları", font=("Segoe UI", 16)).pack(anchor="w")
        ui.Label(self.container, text="Hedef skor").pack(anchor="w")
        self.score = ui.Entry(self.container, name="Hedef skor")
        self.score.insert(0, str(self.profile["score"]))
        self.score.pack(fill="x", pady=5)
        self.score.bind('<FocusOut>', self.remember_settings)
        self.shield = self.setting_toggle('Kalkan', bool(self.profile['shield']))
        self.silent = self.setting_toggle('Rastgele sessiz top', bool(self.profile['silent_ball']))
        ui.Label(self.container, text="Bot zorluğu").pack(anchor="w")
        self.difficulty = ui.ComboBox(self.container, values=list(Bot.LEVELS), name="Bot zorluğu", state="readonly")
        self.difficulty.set(str(self.profile["difficulty"]))
        self.difficulty.pack(fill="x", pady=5)
        self.difficulty.bind('<<ComboboxSelected>>', self.remember_settings)
        self.error = ui.Label(self.container, text="", foreground="#a22")
        self.error.pack(anchor="w")
        ui.Button(self.container, text="Başla", command=self.start).pack(fill="x", pady=15)
        self.score.focus_set()

    def start(self) -> None:
        name = str(self.profile["name"])
        try:
            rules = Rules(score=int(self.score.get()), shield=self.shield.get(),
                          silent_ball=self.silent.get())
        except (ValueError, TypeError):
            self.error.config(text="Hedef skor pozitif bir tam sayı olmalı.")
            return
        level = self.difficulty.get()
        if level not in Bot.LEVELS:
            self.error.config(text="Bot zorluğu seç.")
            return
        self.profile = {"name": name, "score": rules.score, "shield": rules.shield,
                        "silent_ball": rules.silent_ball, "difficulty": level}
        PROFILE.parent.mkdir(parents=True, exist_ok=True)
        PROFILE.write_text(json.dumps(self.profile, ensure_ascii=False), encoding="utf-8")
        self.match = Match(rules)
        self.audio.reset()
        self.audio.music(None)
        self.audio.play_file('announcer/gamestart.wav')
        self.bot = Bot(level)
        self.pressed.clear()
        self.clear()
        self.score_label = ui.Label(self.container, text="Skor 0 - 0", font=("Segoe UI", 16))
        self.score_label.pack(anchor="w", pady=5)
        self.status = ui.Label(self.container, text="Servis ve vuruş için yukarı ok veya boşluk.")
        self.status.pack(anchor="w", pady=5)
        self.canvas = ui.Canvas(self.container, background="#10202b", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, pady=8)
        self.install_mouse_controls()
        ui.Button(self.container, text="Ana menü", command=self.menu).pack(fill="x")
        self.canvas.focus_set()
        self.root.title("DragonPong Kaynak Klon - Maç başladı")
        self.last_tick = time.perf_counter()
        self.draw()

    def online_menu(self, spectator: bool = False) -> None:
        name = self.name.get().strip()
        if not 1 <= len(name) <= 24:
            self.error.config(text="Önce 1 ile 24 karakter arasında ad yaz.")
            return
        self.profile["name"] = name
        self.browsing_spectator = spectator
        PROFILE.parent.mkdir(parents=True, exist_ok=True)
        PROFILE.write_text(json.dumps(self.profile, ensure_ascii=False), encoding="utf-8")
        try:
            self.connection = Connection()
        except OSError as exc:
            self.error.config(text=f"Sunucuya bağlanılamadı: {exc}")
            return
        self.clear()
        self.root.title("DragonPong Kaynak Klon - Odalar")
        ui.Label(self.container, text="Odalar", font=("Segoe UI", 17)).pack(anchor="w")
        self.rooms_list = ui.ListBox(self.container, height=12)
        self.rooms_list.pack(fill="both", expand=True, pady=12)
        self.rooms_list.bind('<Return>', lambda _e: (self.spectate_room() if spectator else self.join_room(), 'break')[1])
        if spectator:
            ui.Button(self.container, text="Seçili odayı izle", command=self.spectate_room).pack(fill="x", pady=3)
        else:
            ui.Button(self.container, text="Seçili odaya oyuncu olarak bağlan", command=self.join_room).pack(fill="x", pady=3)
            ui.Button(self.container, text="Yeni oda oluştur ve eş bekle", command=lambda: self.enter_room("create")).pack(fill="x", pady=3)
        ui.Button(self.container, text="Yenile", command=lambda: self.send_online("rooms")).pack(fill="x", pady=3)
        ui.Button(self.container, text="Ana menü", command=self.menu).pack(fill="x", pady=3)
        if not self.send_online("rooms"):
            return
        self.rooms_list.focus_set()

    def join_room(self) -> None:
        if not self.rooms_list.curselection():
            self.root.bell()
            return
        index = self.rooms_list.curselection()[0]
        if index >= len(self.online_rooms):
            self.enter_room('create')
            return
        room = self.online_rooms[index]
        if not room["joinable"]:
            self.root.bell()
            return
        self.enter_room("join", room["room_id"])

    def spectate_room(self) -> None:
        if not self.online_rooms or not self.rooms_list.curselection():
            self.root.bell()
            return
        room = self.online_rooms[self.rooms_list.curselection()[0]]
        self.enter_room("spectate", room["room_id"])

    def enter_room(self, kind: str, room_id: str | None = None) -> None:
        if not self.connection:
            return
        if not self.send_online(kind, name=self.profile["name"], room_id=room_id):
            return
        self.clear()
        ui.Label(self.container, text="Odaya bağlanılıyor...", font=("Segoe UI", 16)).pack(anchor="w", pady=12)
        ui.Button(self.container, text="Ana menü", command=self.menu).pack(fill="x", pady=8)

    def character_menu(self) -> None:
        self.root.title('DragonPong - Karakter seçimi')
        self.clear()
        ui.Label(self.container, text="Karakterini seç", font=("Segoe UI", 16)).pack(anchor="w", pady=12)
        self.character = ui.ComboBox(self.container, values=CHARACTERS, name="Karakter",
                                       state="readonly")
        self.character.current(0)
        self.character.bind('<<ComboboxSelected>>', self.character_sound)
        self.audio.music('Music/charselect.wav')
        self.character.pack(fill="x", pady=8)
        ui.Button(self.container, text="Seçimi onayla", command=self.send_character).pack(fill="x")
        self.character.focus_set()

    def send_character(self) -> None:
        if self.connection:
            if not self.send_online("character", value=self.character.current()):
                return
        self.clear()
        ui.Label(self.container, text="Rakibin karakter seçimi bekleniyor...").pack(anchor="w")

    def character_sound(self, _event=None) -> None:
        self.audio.play_file(f'Chars/{self.character.current() + 1}/name.wav')

    def setting_toggle(self, label: str, initial: bool):
        value = ui.BooleanVar(value=initial)
        text = ui.StringVar()
        def update(*_args):
            text.set(f"{label}: {'açık' if value.get() else 'kapalı'}")
        value.trace_add('write', update)
        value.trace_add('write', lambda *_args: self.remember_settings())
        update()
        widget = ui.CheckBox(self.container, textvariable=text, variable=value)
        widget.pack(anchor='w', pady=5)
        widget.bind('<Left>', lambda _event: (value.set(False), 'break')[1])
        widget.bind('<Right>', lambda _event: (value.set(True), 'break')[1])
        return value

    def online_settings(self) -> None:
        self.root.title('DragonPong - Maç ayarları')
        self.audio.music(None)
        if self.online_player != 0:
            self.clear()
            ui.Label(self.container, text="Oda sahibi maç ayarlarını yapıyor...").pack(anchor="w")
            return
        self.clear()
        ui.Label(self.container, text="Maç ayarları", font=("Segoe UI", 16)).pack(anchor="w")
        ui.Label(self.container, text="Hedef skor").pack(anchor="w", pady=5)
        self.score = ui.Entry(self.container, name="Hedef skor")
        self.score.insert(0, str(self.profile["score"]))
        self.score.pack(fill="x")
        self.score.bind('<FocusOut>', self.remember_settings)
        self.shield = self.setting_toggle('Kalkan', bool(self.profile['shield']))
        self.silent = self.setting_toggle('Rastgele sessiz top', bool(self.profile['silent_ball']))
        self.error = ui.Label(self.container, text="", foreground="#a22")
        self.error.pack(anchor="w")
        ui.Button(self.container, text="Ayarları onayla", command=self.configure_online).pack(fill="x", pady=10)
        self.score.focus_set()

    def configure_online(self) -> None:
        try:
            rules = Rules(score=int(self.score.get()), shield=self.shield.get(),
                          silent_ball=self.silent.get())
        except (ValueError, TypeError):
            self.error.config(text="Geçerli pozitif hedef skor yaz.")
            return
        self.profile.update(score=rules.score, shield=rules.shield,
                            silent_ball=rules.silent_ball)
        PROFILE.write_text(json.dumps(self.profile, ensure_ascii=False), encoding="utf-8")
        if self.connection:
            self.send_online("configure", score=rules.score, shield=rules.shield,
                             silent_ball=rules.silent_ball)

    def online_message(self, message: dict) -> None:
        kind = message.get("type")
        if kind == "rooms" and hasattr(self, "rooms_list") and self.rooms_list.winfo_exists():
            rooms = message.get("rooms", [])
            self.online_rooms = rooms if self.browsing_spectator else [r for r in rooms if r.get("joinable")]
            if not self.online_rooms and not self.browsing_spectator:
                self.enter_room("create")
                return
            self.rooms_list.delete(0, "end")
            for room in self.online_rooms:
                label = f"{room['host_name']} eş bekliyor" if room["joinable"] else (
                    f"{room['host_name']} ile {room.get('guest_name') or 'rakibi'} maçta")
                self.rooms_list.insert("end", label)
            if self.online_rooms:
                if not self.browsing_spectator:
                    self.rooms_list.insert('end', 'Yeni oda oluştur ve eş bekle')
                self.rooms_list.selection_set(0)
            else:
                self.rooms_list.insert("end", "Oda yok. Yeni oda oluşturabilirsin.")
                self.online_rooms = []
        elif kind == "accepted":
            self.online_player = message.get("player")
            self.paddle_prediction.reset()
            self.audio.listener = self.online_player if self.online_player is not None else 0
            self.root.title("DragonPong Kaynak Klon - Odaya bağlandı")
            if self.online_player == 0:
                self.clear()
                ui.Label(self.container, text="Oda açıldı. Eş bekleniyor...").pack(anchor="w")
                ui.Button(self.container, text="Ana menü", command=self.menu).pack(fill="x")
            elif self.online_player is None:
                self.clear()
                ui.Label(self.container, text="İzleyici olarak bağlandın. Maç bekleniyor...").pack(anchor="w")
        elif kind == "characters" and self.online_player is not None:
            self.character_menu()
        elif kind == "settings_required" and self.online_player is not None:
            self.online_settings()
        elif kind == "configured":
            self.clear()
            text = (f"Hedef skor {message['score']}. Kalkan "
                    f"{'açık' if message['shield'] else 'kapalı'}. Sessiz top "
                    f"{'açık' if message['silent_ball'] else 'kapalı'}.")
            ui.Label(self.container, text=text, wraplength=500).pack(anchor="w", pady=8)
            if self.online_player == 0:
                ui.Button(self.container, text="Başla", command=lambda: self.send_online("start")).pack(fill="x")
            else:
                ui.Label(self.container, text="Oda sahibi Başla seçeneğini bekliyor.").pack(anchor="w")
        elif kind == "state":
            if self.online_state is None:
                self.online_game_screen()
            self.online_state = message
            if self.online_player is not None and getattr(self.connection, 'supports_step_ack', False) is True:
                acknowledgements = message.get('step_ack')
                if (isinstance(acknowledgements, list) and len(acknowledgements) == 2 and
                        type(acknowledgements[self.online_player]) is int):
                    self.paddle_prediction.acknowledge(acknowledgements[self.online_player])
                else:
                    self.connection.supports_step_ack = False
                    self.paddle_prediction.reset()
            if message.get('winner') is not None:
                self.paddle_prediction.reset()
            self.characters = message.get('characters', [0, 1])
            score = f"Skor {message['scores'][0]} - {message['scores'][1]}"
            self.score_label.config(text=score)
            if self.online_player is not None:
                self.audio.listener_x = self.predicted_paddles()[self.online_player]
            else:
                self.audio.listener_x = message["paddles"][self.audio.listener]
            self.refresh_online_audio()
            for item in message.get("events", []):
                event = Event(**item)
                if not self.audio_error:
                    self.audio.play(event)
                if event.kind == "goal":
                    if message['winner'] is None:
                        self.audio.goal_sequence(event, self.characters, message['scores'])
                    self.announce(f"Gol. Skor {message['scores'][0]} - {message['scores'][1]}")
                elif event.kind == "win":
                    self.audio.match_result(event.player, self.characters)
                    self.announce("Maç bitti.")
        elif kind == 'strike_result':
            errors = {'not_ready': 'Servis sırası veya bekleme süresi uygun değil.',
                      'invalid_view': 'Güncel oyun verisi bekleniyor.',
                      'unknown_view': 'Oyun verisi fazla gecikti.',
                      'stale_view': 'Oyun verisi fazla gecikti.',
                      'wrong_direction': 'Top sana doğru gelmiyor.',
                      'too_late': 'Top vuruş alanını geçti.',
                      'out_of_reach': 'Top raketin yanında kaldı.',
                      'out_of_range': 'Top henüz vuruş alanında değil.'}
            if message.get('result') in errors:
                self.announce('Vuruş olmadı: ' + errors[message['result']])
        elif kind == "perspective":
            self.audio.listener = message["player"]
            if self.online_state:
                self.audio.listener_x = self.online_state['paddles'][self.audio.listener]
            names = self.online_state.get('players', ['Oyuncu 1', 'Oyuncu 2']) if self.online_state else ['Oyuncu 1', 'Oyuncu 2']
            self.announce(f"{names[self.audio.listener]} gözünden izleniyor.")
        elif kind in ("room_closed", "disconnected", "connection_error", "rejected"):
            if self.connection:
                self.menu()
            reason = message.get('reason', 'Oyuncu ayrıldı; oda kapandı.' if kind == 'room_closed' else kind)
            self.error.config(text=f'Bağlantı kapandı: {reason}')
            self.title_message(f'Bağlantı kapandı: {reason}')

    def online_game_screen(self) -> None:
        self.root.title('DragonPong - Çevrimiçi maç')
        self.audio.reset()
        self.audio.music(None)
        self.clear()
        self.score_label = ui.Label(self.container, text="Skor 0 - 0", font=("Segoe UI", 16))
        self.score_label.pack(anchor="w", pady=5)
        self.status = ui.Label(self.container, text="Sol/sağ ok: hareket. Yukarı ok veya boşluk: servis/vuruş. İzleyici sol/sağ okla oyuncu değiştirir.",
                                wraplength=550)
        self.status.pack(anchor="w", pady=5)
        self.canvas = ui.Canvas(self.container, background="#10202b", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, pady=8)
        self.install_mouse_controls()
        ui.Button(self.container, text="Ana menü", command=self.menu).pack(fill="x")
        self.canvas.focus_set()

    def key_down(self, event) -> None:
        if event.keysym.lower() == 'escape':
            self.menu()
            return 'break'
        if event.keysym.lower() == 'f6' and self.connection:
            self.title_message(self.network_text())
            return 'break'
        if not self.match and self.online_state is None:
            return
        key = event.keysym.lower()
        if key in ('prior', 'next'):
            self.audio.music_gain = max(0, min(1, self.audio.music_gain + (.1 if key == 'prior' else -.1)))
            self.announce(f'Müzik sesi yüzde {round(self.audio.music_gain * 100)}')
            return 'break'
        self.pressed.add(key)
        if self.network_stalled() and key in ('space', 'up', 'left', 'right', 'a', 'd'):
            return 'break'
        if key in ("space", "up"):
            if self.match:
                self.match.strike(0)
            elif (self.connection and self.online_player is not None and
                  self.online_state.get('winner') is None):
                fields = {}
                if getattr(self.connection, 'supports_strike_ref', False) is True:
                    fields['view'] = self.presented_view or {
                        'frame': self.online_state.get('frame_id'),
                        'seconds': self.online_view_seconds(self.online_state)}
                self.send_online("strike", **fields)
        elif key == "escape":
            self.menu()
        elif self.online_state is not None and self.online_player is None and key in ("left", "right"):
            self.audio.listener = (self.audio.listener + (1 if key == 'right' else -1)) % 2
            if self.connection:
                self.send_online("perspective", player=self.audio.listener)
        elif key in ('left', 'right', 'a', 'd'):
            direction = 1 if key in ('right', 'd') else -1
            if self.match:
                self.match.move_step(0, direction)
            elif (self.connection and self.online_player is not None and
                  self.online_state.get('winner') is None):
                if (getattr(self.connection, 'supports_step_ack', False) is True and
                        'step_ack' in self.online_state):
                    seq = self.paddle_prediction.add(direction)
                    if not self.send_online('step', direction=direction, seq=seq):
                        return 'break'
                    self.audio.listener_x = self.predicted_paddles()[self.online_player]
                    self.draw()
                else:
                    self.send_online('step', direction=direction)

    def key_up(self, event) -> None:
        self.pressed.discard(event.keysym.lower())

    def tick(self) -> None:
        if self.closing or self.tick_in_progress:
            return
        self.tick_in_progress = True
        try:
            self._tick()
        finally:
            self.tick_in_progress = False

    def _tick(self) -> None:
        active = bool(self.match or self.online_state is not None) and self.root.focus_displayof() is not None
        for key in self.controller.poll(active):
            self.key_down(type('Key', (), {'keysym': key})())
        # SDL can pump native messages, including window close, while polling.
        if self.closing:
            return
        now = time.perf_counter()
        dt = min(.05, max(0.0, now - self.last_tick))
        self.last_tick = now
        connection = self.connection
        if connection:
            for _ in range(100):
                try:
                    message = connection.events.get_nowait()
                except queue.Empty:
                    break
                self.online_message(message)
                if connection is not self.connection:
                    break
        match = self.match
        if match and self.bot:
            self.bot.step(match, dt)
            for event in match.step(dt):
                if not self.audio_error:
                    self.audio.play(event)
                if event.kind == "goal":
                    if match.winner is None:
                        self.audio.goal_sequence(event, self.characters, match.scores)
                    self.announce(f"Gol. Skor {match.scores[0]} - {match.scores[1]}")
                elif event.kind == "win":
                    self.audio.match_result(event.player, self.characters)
                    self.announce("Kazandın!" if event.player == 0 else "Bot kazandı.")
                elif event.kind == "shield_on":
                    self.announce("Kalkan kazanıldı." if event.player == 0 else "Bot kalkan kazandı.")
                elif event.kind == "silent_on":
                    self.announce("Sessiz top etkin.")
            self.score_label.config(text=f"Skor {match.scores[0]} - {match.scores[1]}")
            self.audio.listener_x = match.paddles[0]
            self.audio.set_ball(Event("rolling", match.ball_x, match.ball_z)
                                if match.vz and match.time >= match.silent_until else None)
            self.audio.set_shields([Event('shield_loop', match.paddles[p], p * COURT_LENGTH, player=p)
                                   for p, expiry in enumerate(match.shield_until) if expiry > match.time])
            self.draw()
        elif self.online_state is not None and self.connection:
            if self.network_stalled():
                self.audio.set_ball(None)
                self.audio.set_shields([])
            self.draw()
        self.update_network_notice()
        if self.connection and self.network_label is not None and self.network_label.winfo_exists():
            network_text = self.network_text()
            if self.network_label.cget('text') != network_text:
                self.network_label.config(text=network_text)
        self.root.after(16, self.tick)

    def announce(self, message: str) -> None:
        if self.match or self.online_state is not None:
            self.status.config(text=message)
            self.title_message(message)

    def online_ball(self, state: dict | None = None) -> tuple[float, float]:
        state = state or self.online_state
        if (state.get('winner') is None and
                time.monotonic() - state.get('_received_at', time.monotonic()) > 1):
            return tuple(state['ball'])
        flight = self.present_online(state).flight
        return flight.x, flight.z

    def present_online(self, state: dict):
        return present_flight(state, getattr(self.connection, 'ping_ms', None), time.monotonic(),
                              self.online_player,
                              getattr(self.connection, 'supports_strike_ref', False) is True)

    def online_view_seconds(self, state: dict) -> float:
        return view_seconds(state, getattr(self.connection, 'ping_ms', None), time.monotonic(),
                            getattr(self.connection, 'supports_strike_ref', False) is True)

    def refresh_online_audio(self) -> tuple[float, float]:
        state = self.online_state
        presentation = self.present_online(state)
        flight = presentation.flight
        self.presented_view = {'frame': presentation.source.get('frame_id'), 'seconds': presentation.seconds}
        if self.network_stalled():
            self.audio.set_ball(None)
            self.audio.set_shields([])
            return tuple(state['ball'])
        source = presentation.source
        self.audio.set_ball(Event('rolling', flight.x, flight.z)
                            if any(source['velocity']) and not source['silent'] else None)
        self.audio.set_shields([Event('shield_loop', state['paddles'][p], p * COURT_LENGTH, player=p)
                               for p, active in enumerate(state.get('shields', [])) if active])
        return flight.x, flight.z

    def predicted_paddles(self) -> list[float]:
        paddles = list(self.online_state['paddles'])
        if (self.online_player is not None and
                getattr(self.connection, 'supports_step_ack', False) is True and
                'step_ack' in self.online_state):
            player = self.online_player
            paddles[player] = self.paddle_prediction.position(paddles[player], player)
        return paddles

    def draw(self) -> None:
        if not self.match and self.online_state is None:
            return
        c = self.canvas
        c.delete("all")
        width = max(1, c.winfo_width())
        height = max(1, c.winfo_height())
        margin = 28
        xscale = (width - 2 * margin) / (2 * HALF_WIDTH)
        zscale = (height - 2 * margin) / COURT_LENGTH
        def point(x, z):
            return margin + (x + HALF_WIDTH) * xscale, height - margin - z * zscale
        c.create_rectangle(margin, margin, width - margin, height - margin, outline="#91b9c4", width=2)
        c.create_line(*point(-HALF_WIDTH, 10), *point(HALF_WIDTH, 10), fill="#52717a", dash=(8, 6))
        paddles = self.match.paddles if self.match else self.predicted_paddles()
        ball_x, ball_z = ((self.match.ball_x, self.match.ball_z) if self.match
                          else self.refresh_online_audio())
        for player, z, color in ((0, .3, "#49dca1"), (1, 19.7, "#ffae70")):
            x = paddles[player]
            c.create_line(*point(x - 1.25, z), *point(x + 1.25, z), fill=color, width=10)
        bx, by = point(ball_x, ball_z)
        c.create_oval(bx - 6, by - 6, bx + 6, by + 6, fill="white", outline="")

    def close(self) -> None:
        if self.closing:
            return
        self.closing = True
        if hasattr(self, 'name') and self.name.winfo_exists():
            self.remember_name()
        self.controller.close()
        if self.connection:
            self.connection.close()
        self.audio.close()
        self.root.destroy()


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == '--verify-package':
        import tempfile
        report_path = Path(sys.argv[2]).resolve()
        with tempfile.TemporaryDirectory() as test_directory:
            PROFILE = Path(test_directory) / 'profile.json'
            game = Game()
            game.root.withdraw()
            game.audio.music(None)
            game.offline_character_menu()
            game.offline_settings()
            game.score.delete(0, 'end')
            game.score.insert(0, '30')
            game.start()
            game.audio.reset()
            game.match.serve(0)
            game.match.step(.017)
            report = {'audio_error': game.audio_error,
                      'assets': len(game.audio.bank.files),
                      'score_target': game.match.rules.score,
                      'ball_moving': game.match.vz != 0,
                      'frozen': bool(getattr(sys, 'frozen', False))}
            def finish_verification():
                report['audio_callbacks'] = game.audio.callback_count
                report['callback_errors'] = list(game.root.callback_errors)
                game.close()
                report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            game.root.after(300, finish_verification)
            game.root.mainloop()
            if report.get('callback_errors'):
                raise SystemExit(1)
    else:
        Game().root.mainloop()

from __future__ import annotations

import json
import os
import sys
import ssl
import threading
import traceback
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    import certifi
except Exception:
    certifi = None

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.properties import ListProperty, NumericProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen, ScreenManager, NoTransition
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget


# ============================================================
# CORES / VISUAL
# ============================================================

C_BG = (.025, .055, .095, 1)
C_PANEL = (.055, .105, .17, 1)
C_BORDER = (.16, .28, .40, 1)
C_TEXT = (.94, .97, 1, 1)
C_MUTED = (.56, .66, .77, 1)
C_BLUE = (.18, .52, .98, 1)
C_GREEN = (.13, .78, .52, 1)
C_YELLOW = (1, .72, .20, 1)
C_RED = (1, .35, .40, 1)
C_DARK = (.08, .16, .25, 1)

Window.clearcolor = C_BG


# ============================================================
# DIAGNÓSTICO DE CRASH
# ============================================================

def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def crash_text(exc_text: str) -> str:
    return (
        "APS SERRA - DIAGNÓSTICO DE INICIALIZAÇÃO\n"
        f"Data/Hora: {datetime.now():%d/%m/%Y %H:%M:%S}\n"
        f"Python: {sys.version}\n"
        f"Plataforma: {sys.platform}\n"
        f"Diretório atual: {os.getcwd()}\n"
        "\n"
        "============================================================\n"
        "ERRO\n"
        "============================================================\n\n"
        f"{exc_text}\n"
    )


def save_crash_report(exc_text: str, app=None) -> str:
    """
    Salva o último erro em crash_aps_serra.txt.

    No Android, a primeira tentativa é app.user_data_dir.
    Há fallbacks para o diretório privado do aplicativo e diretório atual.
    """
    payload = crash_text(exc_text)

    candidates = []

    if app is not None:
        try:
            candidates.append(Path(app.user_data_dir))
        except Exception:
            pass

    android_private = os.environ.get("ANDROID_PRIVATE")
    if android_private:
        candidates.append(Path(android_private))

    candidates.append(Path.cwd())

    tried = set()

    for folder in candidates:
        try:
            folder = folder.resolve()
        except Exception:
            pass

        folder_key = str(folder)
        if folder_key in tried:
            continue
        tried.add(folder_key)

        try:
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / "crash_aps_serra.txt"
            path.write_text(payload, encoding="utf-8")
            return str(path)
        except Exception:
            continue

    return "Não foi possível gravar crash_aps_serra.txt"


def diagnostic_root(exc_text: str, file_path: str):
    """
    Tela simples, independente da interface principal.
    Se o erro ocorrer durante ApsSerraTabletApp.build(), o APK fica aberto
    mostrando o traceback em vez de fechar silenciosamente.
    """
    root = BoxLayout(
        orientation="vertical",
        padding=[dp(18), dp(14), dp(18), dp(14)],
        spacing=dp(10),
    )

    title = Label(
        text="ERRO AO INICIAR O APS SERRA",
        color=C_RED,
        bold=True,
        font_size=sp(24),
        size_hint_y=None,
        height=dp(54),
        halign="left",
        valign="middle",
    )
    title.bind(size=lambda instance, _value: setattr(instance, "text_size", instance.size))
    root.add_widget(title)

    subtitle = Label(
        text=(
            "O aplicativo não foi encerrado. O erro abaixo mostra exatamente "
            "o que falhou durante a inicialização."
        ),
        color=C_TEXT,
        font_size=sp(13),
        size_hint_y=None,
        height=dp(54),
        halign="left",
        valign="middle",
    )
    subtitle.bind(
        size=lambda instance, _value: setattr(instance, "text_size", instance.size)
    )
    root.add_widget(subtitle)

    path_label = Label(
        text=f"Arquivo de diagnóstico: {file_path}",
        color=C_MUTED,
        font_size=sp(10),
        size_hint_y=None,
        height=dp(40),
        halign="left",
        valign="middle",
    )
    path_label.bind(
        size=lambda instance, _value: setattr(instance, "text_size", instance.size)
    )
    root.add_widget(path_label)

    report = TextInput(
        text=crash_text(exc_text),
        readonly=True,
        multiline=True,
        background_normal="",
        background_active="",
        background_color=(.02, .035, .055, 1),
        foreground_color=C_TEXT,
        cursor_color=C_BLUE,
        font_size=sp(12),
        padding=[dp(12), dp(12), dp(12), dp(12)],
    )
    root.add_widget(report)

    footer = Label(
        text=(
            "Tire uma foto ou print desta tela e envie para análise. "
            "Não é necessário ADB."
        ),
        color=C_YELLOW,
        bold=True,
        font_size=sp(12),
        size_hint_y=None,
        height=dp(44),
        halign="left",
        valign="middle",
    )
    footer.bind(size=lambda instance, _value: setattr(instance, "text_size", instance.size))
    root.add_widget(footer)

    return root


# ============================================================
# FUNÇÕES GERAIS
# ============================================================

def hhmm(v):
    if not v:
        return "--:--"

    try:
        return datetime.fromisoformat(
            str(v).replace("Z", "+00:00")
        ).strftime("%H:%M")
    except Exception:
        return str(v)[11:16] if len(str(v)) >= 16 else str(v)


def load_cfg():
    data = {}

    candidates = [
        Path(__file__).resolve().parent / "tablet.env",
    ]

    for p in candidates:
        if not p.exists():
            continue

        for line in p.read_text(encoding="utf-8").splitlines():
            s = line.strip()

            if not s or s.startswith("#") or "=" not in s:
                continue

            k, v = s.split("=", 1)
            data[k.strip()] = v.strip().strip('"').strip("'")

    for k in ("SUPABASE_URL", "SUPABASE_ANON_KEY"):
        if os.getenv(k):
            data[k] = os.getenv(k)

    return data


# ============================================================
# COMPONENTES VISUAIS
# ============================================================

class Card(BoxLayout):
    bg_color = ListProperty(C_PANEL)
    border_color = ListProperty(C_BORDER)
    radius = NumericProperty(dp(16))

    def __init__(self, **kw):
        super().__init__(**kw)

        self.padding = kw.get("padding", dp(14))
        self.spacing = kw.get("spacing", dp(8))

        with self.canvas.before:
            Color(*self.border_color)
            self._b = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[self.radius],
            )

            Color(*self.bg_color)
            self._i = RoundedRectangle(
                pos=(self.x + dp(1), self.y + dp(1)),
                size=(
                    max(0, self.width - dp(2)),
                    max(0, self.height - dp(2)),
                ),
                radius=[self.radius],
            )

        self.bind(pos=self._sync, size=self._sync)

    def _sync(self, *_):
        self._b.pos = self.pos
        self._b.size = self.size

        self._i.pos = (
            self.x + dp(1),
            self.y + dp(1),
        )
        self._i.size = (
            max(0, self.width - dp(2)),
            max(0, self.height - dp(2)),
        )


class FlatButton(Button):
    def __init__(self, text="", bg=C_DARK, fg=C_TEXT, **kw):
        super().__init__(text=text, **kw)

        self.background_normal = ""
        self.background_down = ""
        self.background_color = bg
        self.color = fg
        self.bold = True
        self.font_size = sp(14)
        self.size_hint_y = None
        self.height = kw.get("height", dp(52))


class Field(TextInput):
    def __init__(self, **kw):
        super().__init__(**kw)

        self.multiline = False
        self.background_normal = ""
        self.background_active = ""
        self.background_color = (.035, .075, .12, 1)
        self.foreground_color = C_TEXT
        self.hint_text_color = C_MUTED
        self.cursor_color = C_BLUE
        self.padding = [dp(12), dp(12), dp(12), dp(10)]
        self.font_size = sp(16)
        self.size_hint_y = None
        self.height = dp(50)


class Status(Label):
    def __init__(self, text, tone="WAIT", **kw):
        super().__init__(text=text, **kw)

        self.size_hint = (None, None)
        self.height = dp(30)
        self.bold = True
        self.font_size = sp(10)
        self.color = C_TEXT
        self.padding = [dp(10), dp(5)]

        self.texture_update()
        self.width = max(
            dp(86),
            self.texture_size[0] + dp(20),
        )

        c = {
            "OK": (.05, .30, .20, 1),
            "RUN": (.08, .25, .45, 1),
            "WARN": (.34, .24, .06, 1),
            "BAD": (.35, .08, .11, 1),
            "WAIT": (.15, .18, .23, 1),
        }.get(tone, (.15, .18, .23, 1))

        with self.canvas.before:
            Color(*c)
            self._r = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[dp(15)],
            )

        self.bind(pos=self._s, size=self._s)

    def _s(self, *_):
        self._r.pos = self.pos
        self._r.size = self.size


class Progress(Widget):
    value = NumericProperty(0)

    def __init__(self, **kw):
        super().__init__(**kw)

        self.size_hint_y = None
        self.height = dp(12)

        with self.canvas:
            Color(.03, .08, .13, 1)
            self._t = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[dp(7)],
            )

            Color(*C_GREEN)
            self._f = RoundedRectangle(
                pos=self.pos,
                size=(0, self.height),
                radius=[dp(7)],
            )

        self.bind(
            pos=self._s,
            size=self._s,
            value=self._s,
        )

    def _s(self, *_):
        self._t.pos = self.pos
        self._t.size = self.size
        self._f.pos = self.pos

        self._f.size = (
            self.width
            * max(0, min(100, float(self.value)))
            / 100,
            self.height,
        )


def lbl(
    text,
    color=C_MUTED,
    size=sp(12),
    h=dp(30),
    bold=False,
):
    x = Label(
        text=text,
        color=color,
        font_size=size,
        bold=bold,
        size_hint_y=None,
        height=h,
        halign="left",
        valign="middle",
    )

    x.bind(
        size=lambda instance, _value: setattr(
            instance,
            "text_size",
            instance.size,
        )
    )

    return x


# ============================================================
# ARMAZENAMENTO LOCAL
# ============================================================

class LocalStore:
    def __init__(self, app):
        self.path = (
            Path(app.user_data_dir)
            / "aps_serra_tablet_online.json"
        )

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.data = {
            "config": {
                "machine": "SER-01",
                "last_operator": "",
            },
            "orders": [],
            "events": [],
        }

        if self.path.exists():
            try:
                self.data.update(
                    json.loads(
                        self.path.read_text(
                            encoding="utf-8"
                        )
                    )
                )
            except Exception:
                pass

    def save(self):
        self.path.write_text(
            json.dumps(
                self.data,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def event(self, text):
        self.data.setdefault(
            "events",
            [],
        ).insert(
            0,
            {
                "at": now_iso(),
                "text": text,
            },
        )

        self.data["events"] = (
            self.data["events"][:100]
        )

        self.save()


# ============================================================
# SUPABASE
# ============================================================

class SupabaseAPI:
    def __init__(self, cfg):
        self.url = (
            cfg.get(
                "SUPABASE_URL",
                "",
            ).rstrip("/")
        )

        self.anon = cfg.get(
            "SUPABASE_ANON_KEY",
            "",
        )

    @property
    def configured(self):
        return bool(
            self.url
            and self.anon
        )

    def rpc(
        self,
        name,
        payload=None,
        timeout=15,
    ):
        if not self.configured:
            raise RuntimeError(
                "SUPABASE_URL / SUPABASE_ANON_KEY "
                "não configurados em tablet.env."
            )

        body = json.dumps(
            dict(payload or {}),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

        req = Request(
            f"{self.url}/rest/v1/rpc/{name}",
            data=body,
            headers={
                "apikey": self.anon,
                "Authorization": (
                    f"Bearer {self.anon}"
                ),
                "Content-Type": (
                    "application/json"
                ),
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            ssl_context = None

            if self.url.lower().startswith("https://"):
                if certifi is not None:
                    ssl_context = ssl.create_default_context(
                        cafile=certifi.where()
                    )
                else:
                    ssl_context = ssl.create_default_context()

            if ssl_context is not None:
                response = urlopen(
                    req,
                    timeout=timeout,
                    context=ssl_context,
                )
            else:
                response = urlopen(
                    req,
                    timeout=timeout,
                )

            with response as resp:
                raw = (
                    resp.read()
                    .decode("utf-8")
                )

                if not raw.strip():
                    return None

                return json.loads(raw)

        except HTTPError as exc:
            raw = exc.read().decode(
                "utf-8",
                errors="replace",
            )

            raise RuntimeError(
                f"HTTP {exc.code}: "
                f"{raw[:500]}"
            ) from exc

        except URLError as exc:
            reason = getattr(
                exc,
                "reason",
                exc,
            )

            raise RuntimeError(
                "Falha de conexão com "
                f"o Supabase: {reason}"
            ) from exc

        except TimeoutError as exc:
            raise RuntimeError(
                "Tempo esgotado ao comunicar "
                "com o Supabase."
            ) from exc

    def machines(self):
        return self.rpc(
            "aps_tablet_maquinas"
        )

    def queue(self, machine):
        return self.rpc(
            "aps_tablet_fila_serra",
            {
                "p_maquina": machine,
            },
        )

    def start(
        self,
        operation_id,
        machine,
        operator,
        setup,
        device_id,
    ):
        return self.rpc(
            "aps_tablet_iniciar_execucao",
            {
                "p_operacao_id": int(
                    operation_id
                ),
                "p_maquina": machine,
                "p_operador": operator,
                "p_setup": bool(setup),
                "p_device_id": device_id,
            },
        )

    def finish_setup(
        self,
        execution_id,
    ):
        return self.rpc(
            "aps_tablet_finalizar_setup",
            {
                "p_execucao_id": (
                    execution_id
                ),
            },
        )

    def pause(
        self,
        execution_id,
    ):
        return self.rpc(
            "aps_tablet_pausar",
            {
                "p_execucao_id": (
                    execution_id
                ),
            },
        )

    def resume(
        self,
        execution_id,
    ):
        return self.rpc(
            "aps_tablet_retomar",
            {
                "p_execucao_id": (
                    execution_id
                ),
            },
        )

    def finish(
        self,
        execution_id,
        good,
        scrap,
        note,
    ):
        return self.rpc(
            "aps_tablet_finalizar_execucao",
            {
                "p_execucao_id": (
                    execution_id
                ),
                "p_quantidade_boa": float(
                    good
                ),
                "p_quantidade_refugo": float(
                    scrap
                ),
                "p_observacao": (
                    note or ""
                ),
            },
        )

    def history(
        self,
        machine,
    ):
        return self.rpc(
            "aps_tablet_historico",
            {
                "p_maquina": machine,
                "p_limite": 50,
            },
        )


# ============================================================
# TELA PRINCIPAL
# ============================================================

class OperationScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)

        self.busy = False
        self.orders = []
        self.active_execution_id = None

        root = BoxLayout(
            orientation="vertical",
            padding=[
                dp(14),
                dp(10),
                dp(14),
                dp(12),
            ],
            spacing=dp(9),
        )
        self.add_widget(root)

        self.header = BoxLayout(
            size_hint_y=None,
            height=dp(78),
        )
        root.add_widget(self.header)

        self.identity = Card(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(72),
            padding=[
                dp(12),
                dp(9),
            ],
            spacing=dp(8),
        )
        root.add_widget(self.identity)

        self.nav = BoxLayout(
            size_hint_y=None,
            height=dp(46),
            spacing=dp(8),
        )
        root.add_widget(self.nav)

        self.content = BoxLayout(
            orientation="vertical"
        )
        root.add_widget(self.content)

        self.build_identity()
        self.build_nav()

    def on_pre_enter(self, *_):
        self.render_header()
        self.load_cached()

        Clock.schedule_once(
            lambda *_: self.refresh_remote(),
            .4,
        )

    def render_header(self):
        self.header.clear_widgets()

        app = App.get_running_app()

        c = Card(
            orientation="horizontal",
            padding=[
                dp(16),
                dp(9),
            ],
        )

        left = BoxLayout(
            orientation="vertical"
        )

        left.add_widget(
            lbl(
                "APS SERRA · OPERAÇÃO",
                C_TEXT,
                sp(21),
                dp(34),
                True,
            )
        )

        left.add_widget(
            lbl(
                (
                    "Programação congelada · "
                    f"{datetime.now():%d/%m/%Y}"
                ),
                C_MUTED,
                sp(11),
                dp(22),
            )
        )

        c.add_widget(left)
        c.add_widget(Widget())

        c.add_widget(
            Status(
                "ONLINE"
                if app.online
                else "OFFLINE",
                "OK"
                if app.online
                else "BAD",
            )
        )

        self.header.add_widget(c)

    def build_identity(self):
        self.identity.clear_widgets()

        app = App.get_running_app()

        opbox = BoxLayout(
            orientation="vertical",
            size_hint_x=.43,
            spacing=dp(2),
        )

        opbox.add_widget(
            lbl(
                "NOME DO OPERADOR · OBRIGATÓRIO",
                C_TEXT,
                sp(10),
                dp(18),
                True,
            )
        )

        self.operator = Field(
            hint_text="Digite seu nome completo"
        )

        self.operator.text = (
            app.store.data["config"].get(
                "last_operator",
                "",
            )
        )

        opbox.add_widget(self.operator)

        mbox = BoxLayout(
            orientation="vertical",
            size_hint_x=.27,
            spacing=dp(2),
        )

        mbox.add_widget(
            lbl(
                "MÁQUINA",
                C_TEXT,
                sp(10),
                dp(18),
                True,
            )
        )

        self.machine = Spinner(
            text=app.store.data[
                "config"
            ].get(
                "machine",
                "SER-01",
            ),
            values=(
                "SER-01",
                "SER-02",
                "SER-03",
                "SER-04",
                "SER-05",
            ),
            background_normal="",
            background_color=C_DARK,
            color=C_TEXT,
            size_hint_y=None,
            height=dp(50),
            font_size=sp(15),
        )

        mbox.add_widget(self.machine)

        btn = FlatButton(
            "CARREGAR FILA",
            bg=C_BLUE,
            size_hint_x=.25,
            height=dp(50),
        )

        btn.bind(
            on_release=lambda *_:
            self.apply_identity()
        )

        self.identity.add_widget(opbox)
        self.identity.add_widget(mbox)
        self.identity.add_widget(btn)

    def build_nav(self):
        self.nav.clear_widgets()

        for t, fn in [
            (
                "OPERAÇÃO",
                self.show_operation,
            ),
            (
                "FILA",
                self.show_queue,
            ),
            (
                "HISTÓRICO",
                self.show_history,
            ),
        ]:
            b = FlatButton(t)
            b.bind(on_release=fn)
            self.nav.add_widget(b)

    def operator_ok(self, show=True):
        name = self.operator.text.strip()

        if not name and show:
            self.popup(
                "OPERADOR OBRIGATÓRIO",
                (
                    "Informe o nome do operador "
                    "antes de executar qualquer ação."
                ),
            )

        return bool(name)

    def apply_identity(self):
        if not self.operator_ok():
            return

        app = App.get_running_app()

        try:
            app.operator = (
                self.operator.text.strip()
            )
            app.machine = self.machine.text

            app.store.data["config"] = {
                "machine": app.machine,
                "last_operator": (
                    app.operator
                ),
            }

            app.store.save()
            self.refresh_remote()

        except Exception as e:
            app.online = False

            try:
                save_crash_report(
                    traceback.format_exc(),
                    app,
                )
            except Exception:
                pass

            self.popup(
                "ERRO AO CARREGAR FILA",
                str(e),
            )

    def load_cached(self):
        app = App.get_running_app()

        self.orders = (
            app.store.data.get(
                "orders",
                [],
            )
        )

        self.show_operation()

    def refresh_remote(self):
        if self.busy:
            return

        if not self.operator_ok(False):
            self.show_operation()
            return

        app = App.get_running_app()

        app.operator = (
            self.operator.text.strip()
        )
        app.machine = self.machine.text

        self.busy = True

        def work():
            try:
                data = app.api.queue(
                    app.machine
                )

                if isinstance(
                    data,
                    dict,
                ):
                    rows = (
                        data.get(
                            "orders",
                            [],
                        )
                        or []
                    )
                    plan = (
                        data.get(
                            "plan",
                            {},
                        )
                    )
                else:
                    rows = data or []
                    plan = {}

                Clock.schedule_once(
                    lambda *_args, rows=rows, plan=plan:
                    self._refresh_ok(
                        rows,
                        plan,
                    ),
                    0,
                )

            except Exception as e:
                # IMPORTANTE:
                # A variável de exceção "e" é apagada pelo Python ao sair
                # do bloco except. Se ela for usada diretamente dentro de
                # um lambda executado depois pelo Clock, o callback pode
                # gerar NameError e derrubar o processo do Kivy.
                error_message = str(e)
                error_trace = traceback.format_exc()

                try:
                    save_crash_report(
                        error_trace,
                        app,
                    )
                except Exception:
                    pass

                Clock.schedule_once(
                    lambda *_args, msg=error_message:
                    self._refresh_fail(msg),
                    0,
                )

        threading.Thread(
            target=work,
            daemon=True,
        ).start()

    def _refresh_ok(
        self,
        rows,
        plan,
    ):
        app = App.get_running_app()

        self.busy = False
        app.online = True
        self.orders = rows

        app.store.data["orders"] = rows
        app.store.data["plan"] = plan

        app.store.save()

        self.render_header()
        self.show_operation()

    def _refresh_fail(
        self,
        msg,
    ):
        app = App.get_running_app()

        self.busy = False
        app.online = False

        try:
            self.render_header()
        except Exception:
            pass

        try:
            app.store.event(
                f"Falha de comunicação: {msg}"
            )
        except Exception:
            pass

        try:
            self.show_operation()
        except Exception:
            pass

        try:
            self.popup(
                "SEM COMUNICAÇÃO",
                (
                    "Não foi possível atualizar "
                    "o Supabase.\n\n"
                    f"{msg}\n\n"
                    "A última fila salva permanece "
                    "visível."
                ),
            )
        except Exception:
            # Último fallback: se até o Popup falhar, substitui o conteúdo
            # por uma mensagem simples sem encerrar o aplicativo.
            try:
                self.content.clear_widgets()
                self.content.add_widget(
                    lbl(
                        "ERRO AO CARREGAR FILA",
                        C_RED,
                        sp(20),
                        dp(50),
                        True,
                    )
                )
                self.content.add_widget(
                    lbl(
                        str(msg),
                        C_TEXT,
                        sp(12),
                        dp(120),
                    )
                )
            except Exception:
                pass

    def current(self):
        opened = [
            r
            for r in self.orders
            if str(
                r.get(
                    "status",
                    "",
                )
            ).upper()
            != "CONCLUIDA"
        ]

        opened.sort(
            key=lambda r:
            int(
                r.get(
                    "seq",
                    999999,
                )
                or 999999
            )
        )

        return (
            opened[0]
            if opened
            else None
        )

    def tone(self, s):
        s = str(s).upper()

        if s in (
            "EM_PRODUCAO",
            "EM PRODUCAO",
            "EM_SETUP",
            "EM SETUP",
        ):
            return "RUN"

        if s == "CONCLUIDA":
            return "OK"

        if s in (
            "PAUSADA",
            "PARCIAL",
        ):
            return "WARN"

        if s == "BLOQUEADA":
            return "BAD"

        return "WAIT"

    def cell(
        self,
        title,
        value,
    ):
        c = Card(
            orientation="vertical",
            padding=[
                dp(10),
                dp(6),
            ],
            spacing=0,
            radius=dp(11),
            bg_color=(
                .035,
                .075,
                .12,
                1,
            ),
        )

        c.add_widget(
            lbl(
                title,
                C_MUTED,
                sp(9),
                dp(24),
                True,
            )
        )

        c.add_widget(
            lbl(
                value,
                C_TEXT,
                sp(16),
                dp(32),
                True,
            )
        )

        return c

    def show_operation(self, *_):
        self.content.clear_widgets()

        app = App.get_running_app()

        if not self.operator.text.strip():
            c = Card(
                orientation="vertical",
                padding=dp(24),
            )

            c.add_widget(
                lbl(
                    "IDENTIFIQUE O OPERADOR",
                    C_TEXT,
                    sp(25),
                    dp(50),
                    True,
                )
            )

            c.add_widget(
                lbl(
                    (
                        "Informe o nome e escolha "
                        "a máquina no topo. "
                        "Não há senha nem tela de login."
                    ),
                    C_MUTED,
                    sp(14),
                    dp(54),
                )
            )

            self.content.add_widget(c)
            return

        o = self.current()

        if not o:
            c = Card(
                orientation="vertical"
            )

            c.add_widget(
                lbl(
                    "FILA CONCLUÍDA",
                    C_GREEN,
                    sp(27),
                    dp(60),
                    True,
                )
            )

            c.add_widget(
                lbl(
                    (
                        "Nenhuma ordem aberta "
                        f"para {app.machine}."
                    ),
                    C_MUTED,
                    sp(14),
                    dp(40),
                )
            )

            self.content.add_widget(c)
            return

        self.content.add_widget(
            lbl(
                "ORDEM ATUAL",
                C_BLUE,
                sp(11),
                dp(24),
                True,
            )
        )

        c = Card(
            orientation="vertical",
            padding=dp(17),
            spacing=dp(9),
        )

        top = BoxLayout(
            size_hint_y=None,
            height=dp(66),
        )

        left = BoxLayout(
            orientation="vertical"
        )

        left.add_widget(
            lbl(
                f'OP {o.get("op", "")}',
                C_TEXT,
                sp(24),
                dp(34),
                True,
            )
        )

        left.add_widget(
            lbl(
                (
                    f'{o.get("item", "")} · '
                    f'{o.get("description", "")}'
                ),
                C_MUTED,
                sp(12),
                dp(28),
            )
        )

        top.add_widget(left)

        top.add_widget(
            Status(
                str(
                    o.get(
                        "status",
                        "AGUARDANDO",
                    )
                ),
                self.tone(
                    o.get("status")
                ),
            )
        )

        c.add_widget(top)

        planned = float(
            o.get(
                "planned_qty",
                0,
            )
            or 0
        )

        done = float(
            o.get(
                "done_qty",
                0,
            )
            or 0
        )

        saldo = max(
            0,
            planned - done,
        )

        g = GridLayout(
            cols=4,
            size_hint_y=None,
            height=dp(78),
            spacing=dp(8),
        )

        g.add_widget(
            self.cell(
                "SEQUÊNCIA",
                (
                    f'{int(o.get("seq", 0) or 0):02d}'
                ),
            )
        )

        g.add_widget(
            self.cell(
                "PROGRAMADO",
                f"{planned:g} pç",
            )
        )

        g.add_widget(
            self.cell(
                "REALIZADO",
                f"{done:g} pç",
            )
        )

        g.add_widget(
            self.cell(
                "SALDO",
                f"{saldo:g} pç",
            )
        )

        c.add_widget(g)

        c.add_widget(
            Progress(
                value=(
                    100
                    * done
                    / max(
                        1,
                        planned,
                    )
                )
            )
        )

        active = o.get(
            "active_execution_id"
        )

        self.active_execution_id = active

        actions = BoxLayout(
            size_hint_y=None,
            height=dp(60),
            spacing=dp(10),
        )

        s = str(
            o.get(
                "status",
                "",
            )
        ).upper()

        if s in (
            "AGUARDANDO",
            "PARCIAL",
        ):
            b = FlatButton(
                "INICIAR ORDEM",
                bg=C_BLUE,
                height=dp(58),
            )

            b.bind(
                on_release=lambda *_:
                self.ask_setup(o)
            )

            actions.add_widget(b)

        elif s in (
            "EM_SETUP",
            "EM SETUP",
        ):
            b = FlatButton(
                "FINALIZAR SETUP",
                bg=C_YELLOW,
                fg=(
                    .05,
                    .06,
                    .08,
                    1,
                ),
                height=dp(58),
            )

            b.bind(
                on_release=lambda *_:
                self.command(
                    "setup",
                    o,
                )
            )

            actions.add_widget(b)

        elif s in (
            "EM_PRODUCAO",
            "EM PRODUCAO",
        ):
            p = FlatButton(
                "PAUSAR",
                height=dp(58),
            )

            p.bind(
                on_release=lambda *_:
                self.command(
                    "pause",
                    o,
                )
            )

            f = FlatButton(
                "FINALIZAR APONTAMENTO",
                bg=C_GREEN,
                height=dp(58),
            )

            f.bind(
                on_release=lambda *_:
                self.finish_popup(o)
            )

            actions.add_widget(p)
            actions.add_widget(f)

        elif s == "PAUSADA":
            r = FlatButton(
                "RETOMAR",
                bg=C_BLUE,
                height=dp(58),
            )

            r.bind(
                on_release=lambda *_:
                self.command(
                    "resume",
                    o,
                )
            )

            f = FlatButton(
                "FINALIZAR APONTAMENTO",
                bg=C_GREEN,
                height=dp(58),
            )

            f.bind(
                on_release=lambda *_:
                self.finish_popup(o)
            )

            actions.add_widget(r)
            actions.add_widget(f)

        c.add_widget(actions)
        self.content.add_widget(c)

    def ask_setup(
        self,
        o,
    ):
        if not self.operator_ok():
            return

        box = BoxLayout(
            orientation="vertical",
            padding=dp(20),
            spacing=dp(12),
        )

        box.add_widget(
            lbl(
                "INICIAR ORDEM",
                C_TEXT,
                sp(22),
                dp(42),
                True,
            )
        )

        box.add_widget(
            lbl(
                "Esta ordem exige setup?",
                C_MUTED,
                sp(14),
                dp(40),
            )
        )

        row = BoxLayout(
            size_hint_y=None,
            height=dp(60),
            spacing=dp(10),
        )

        no = FlatButton(
            "SEM SETUP",
            bg=C_BLUE,
        )

        yes = FlatButton(
            "COM SETUP",
            bg=C_YELLOW,
            fg=(
                .05,
                .06,
                .08,
                1,
            ),
        )

        row.add_widget(no)
        row.add_widget(yes)

        box.add_widget(row)

        pop = Popup(
            title="",
            content=box,
            size_hint=(.7, .5),
            separator_height=0,
        )

        no.bind(
            on_release=lambda *_:
            (
                pop.dismiss(),
                self.start_remote(
                    o,
                    False,
                ),
            )
        )

        yes.bind(
            on_release=lambda *_:
            (
                pop.dismiss(),
                self.start_remote(
                    o,
                    True,
                ),
            )
        )

        pop.open()

    def start_remote(
        self,
        o,
        setup,
    ):
        app = App.get_running_app()

        try:
            app.api.start(
                o["operation_id"],
                app.machine,
                self.operator.text.strip(),
                setup,
                app.device_id,
            )

            app.online = True

            app.store.event(
                (
                    f'OP {o.get("op")}: '
                    "início confirmado no Supabase."
                )
            )

            self.refresh_remote()

        except Exception as e:
            app.online = False
            self.render_header()

            self.popup(
                "FALHA AO INICIAR",
                str(e),
            )

    def command(
        self,
        kind,
        o,
    ):
        app = App.get_running_app()

        exec_id = o.get(
            "active_execution_id"
        )

        if not exec_id:
            self.popup(
                "SEM EXECUÇÃO",
                (
                    "Não foi encontrada execução "
                    "ativa no Supabase."
                ),
            )
            return

        try:
            {
                "setup": (
                    app.api.finish_setup
                ),
                "pause": (
                    app.api.pause
                ),
                "resume": (
                    app.api.resume
                ),
            }[kind](exec_id)

            app.store.event(
                (
                    f'OP {o.get("op")}: '
                    f"comando {kind} confirmado."
                )
            )

            self.refresh_remote()

        except Exception as e:
            self.popup(
                "ERRO DE COMUNICAÇÃO",
                str(e),
            )

    def finish_popup(
        self,
        o,
    ):
        balance = max(
            0,
            float(
                o.get(
                    "planned_qty",
                    0,
                )
                or 0
            )
            - float(
                o.get(
                    "done_qty",
                    0,
                )
                or 0
            ),
        )

        box = BoxLayout(
            orientation="vertical",
            padding=dp(18),
            spacing=dp(7),
        )

        box.add_widget(
            lbl(
                "FINALIZAR APONTAMENTO",
                C_TEXT,
                sp(22),
                dp(40),
                True,
            )
        )

        g = GridLayout(
            cols=2,
            size_hint_y=None,
            height=dp(120),
            spacing=dp(8),
        )

        a = BoxLayout(
            orientation="vertical"
        )
        b = BoxLayout(
            orientation="vertical"
        )

        a.add_widget(
            lbl(
                "QUANTIDADE BOA",
                C_TEXT,
                sp(10),
                dp(24),
                True,
            )
        )

        qty = Field(
            text=f"{balance:g}",
            input_filter="float",
        )
        a.add_widget(qty)

        b.add_widget(
            lbl(
                "REFUGO",
                C_TEXT,
                sp(10),
                dp(24),
                True,
            )
        )

        scrap = Field(
            text="0",
            input_filter="float",
        )
        b.add_widget(scrap)

        g.add_widget(a)
        g.add_widget(b)
        box.add_widget(g)

        note = Field(
            hint_text="Observação opcional"
        )
        box.add_widget(note)

        msg = lbl(
            "",
            C_RED,
            sp(11),
            dp(24),
        )
        box.add_widget(msg)

        row = BoxLayout(
            size_hint_y=None,
            height=dp(58),
            spacing=dp(8),
        )

        back = FlatButton("VOLTAR")

        ok = FlatButton(
            "CONFIRMAR",
            bg=C_GREEN,
        )

        row.add_widget(back)
        row.add_widget(ok)
        box.add_widget(row)

        pop = Popup(
            title="",
            content=box,
            size_hint=(.78, .78),
            separator_height=0,
        )

        back.bind(
            on_release=lambda *_:
            pop.dismiss()
        )

        def confirm(*_):
            try:
                q = float(
                    qty.text.replace(
                        ",",
                        ".",
                    )
                )

                r = float(
                    scrap.text.replace(
                        ",",
                        ".",
                    )
                )

            except Exception:
                msg.text = (
                    "Quantidades inválidas."
                )
                return

            if q <= 0 or r < 0:
                msg.text = (
                    "Quantidade boa deve ser "
                    "maior que zero."
                )
                return

            exec_id = o.get(
                "active_execution_id"
            )

            try:
                App.get_running_app().api.finish(
                    exec_id,
                    q,
                    r,
                    note.text.strip(),
                )

                pop.dismiss()

                App.get_running_app().store.event(
                    (
                        f'OP {o.get("op")}: '
                        f"{q:g} peças apontadas."
                    )
                )

                self.refresh_remote()

            except Exception as e:
                msg.text = str(e)[:160]

        ok.bind(
            on_release=confirm
        )

        pop.open()

    def show_queue(self, *_):
        self.content.clear_widgets()

        self.content.add_widget(
            lbl(
                "FILA OFICIAL DA MÁQUINA",
                C_BLUE,
                sp(11),
                dp(24),
                True,
            )
        )

        sc = ScrollView(
            do_scroll_x=False
        )

        stack = GridLayout(
            cols=1,
            spacing=dp(7),
            size_hint_y=None,
        )

        stack.bind(
            minimum_height=stack.setter(
                "height"
            )
        )

        for o in sorted(
            self.orders,
            key=lambda x:
            int(
                x.get(
                    "seq",
                    999999,
                )
                or 999999
            ),
        ):
            c = Card(
                orientation="horizontal",
                size_hint_y=None,
                height=dp(88),
                padding=[
                    dp(12),
                    dp(9),
                ],
                spacing=dp(8),
            )

            c.add_widget(
                lbl(
                    (
                        f'{int(o.get("seq", 0) or 0):02d}'
                    ),
                    C_BLUE,
                    sp(18),
                    dp(60),
                    True,
                )
            )

            mid = BoxLayout(
                orientation="vertical"
            )

            mid.add_widget(
                lbl(
                    f'OP {o.get("op", "")}',
                    C_TEXT,
                    sp(14),
                    dp(30),
                    True,
                )
            )

            mid.add_widget(
                lbl(
                    (
                        f'{o.get("item", "")} · '
                        f'{o.get("description", "")}'
                    ),
                    C_MUTED,
                    sp(10),
                    dp(28),
                )
            )

            c.add_widget(mid)

            c.add_widget(
                lbl(
                    (
                        f'{float(o.get("done_qty", 0) or 0):g}/'
                        f'{float(o.get("planned_qty", 0) or 0):g} pç'
                    ),
                    C_TEXT,
                    sp(12),
                    dp(55),
                    True,
                )
            )

            c.add_widget(
                Status(
                    str(
                        o.get(
                            "status",
                            "",
                        )
                    ),
                    self.tone(
                        o.get("status")
                    ),
                )
            )

            stack.add_widget(c)

        sc.add_widget(stack)
        self.content.add_widget(sc)

    def show_history(self, *_):
        self.content.clear_widgets()

        app = App.get_running_app()

        self.content.add_widget(
            lbl(
                "HISTÓRICO DO TABLET",
                C_BLUE,
                sp(11),
                dp(24),
                True,
            )
        )

        sc = ScrollView(
            do_scroll_x=False
        )

        stack = GridLayout(
            cols=1,
            spacing=dp(6),
            size_hint_y=None,
        )

        stack.bind(
            minimum_height=stack.setter(
                "height"
            )
        )

        for e in app.store.data.get(
            "events",
            [],
        ):
            c = Card(
                orientation="horizontal",
                size_hint_y=None,
                height=dp(58),
                padding=[
                    dp(10),
                    dp(7),
                ],
            )

            c.add_widget(
                lbl(
                    hhmm(
                        e.get("at")
                    ),
                    C_BLUE,
                    sp(10),
                    dp(40),
                    True,
                )
            )

            c.add_widget(
                lbl(
                    e.get(
                        "text",
                        "",
                    ),
                    C_TEXT,
                    sp(10),
                    dp(40),
                )
            )

            stack.add_widget(c)

        sc.add_widget(stack)
        self.content.add_widget(sc)

    def popup(
        self,
        title,
        text,
    ):
        box = BoxLayout(
            orientation="vertical",
            padding=dp(20),
            spacing=dp(12),
        )

        box.add_widget(
            lbl(
                title,
                C_TEXT,
                sp(20),
                dp(42),
                True,
            )
        )

        box.add_widget(
            lbl(
                text,
                C_MUTED,
                sp(13),
                dp(110),
            )
        )

        b = FlatButton(
            "OK",
            bg=C_BLUE,
        )

        box.add_widget(b)

        p = Popup(
            title="",
            content=box,
            size_hint=(.7, .55),
            separator_height=0,
        )

        b.bind(
            on_release=lambda *_:
            p.dismiss()
        )

        p.open()


# ============================================================
# APP
# ============================================================

class ApsSerraTabletApp(App):
    title = "APS Serra - Operação"

    def build(self):
        """
        Toda a inicialização principal fica protegida.

        Se ocorrer um erro Python durante a criação do app/tela,
        retornamos uma tela de diagnóstico em vez de deixar o
        Android encerrar o processo silenciosamente.
        """
        try:
            self.store = LocalStore(self)

            cfg = load_cfg()
            self.api = SupabaseAPI(cfg)

            self.online = False

            self.operator = (
                self.store.data[
                    "config"
                ].get(
                    "last_operator",
                    "",
                )
            )

            self.machine = (
                self.store.data[
                    "config"
                ].get(
                    "machine",
                    "SER-01",
                )
            )

            self.device_id = (
                "ANDROID-"
                + os.environ.get(
                    "ANDROID_ARGUMENT",
                    "TABLET",
                )
            )

            sm = ScreenManager(
                transition=NoTransition()
            )

            sm.add_widget(
                OperationScreen(
                    name="operation"
                )
            )

            sm.current = "operation"

            return sm

        except BaseException:
            tb = traceback.format_exc()

            file_path = save_crash_report(
                tb,
                self,
            )

            return diagnostic_root(
                tb,
                file_path,
            )


def _global_excepthook(
    exc_type,
    exc_value,
    exc_tb,
):
    """
    Registra qualquer exceção não tratada que consiga chegar
    ao excepthook padrão do Python.
    """
    try:
        text = "".join(
            traceback.format_exception(
                exc_type,
                exc_value,
                exc_tb,
            )
        )

        app = App.get_running_app()

        save_crash_report(
            text,
            app,
        )
    except Exception:
        pass

    sys.__excepthook__(
        exc_type,
        exc_value,
        exc_tb,
    )


sys.excepthook = _global_excepthook


if __name__ == "__main__":
    try:
        ApsSerraTabletApp().run()

    except BaseException:
        # Se a falha ocorrer fora do build(), ainda tentamos
        # deixar um arquivo de diagnóstico no armazenamento privado.
        try:
            save_crash_report(
                traceback.format_exc()
            )
        except Exception:
            pass

        raise

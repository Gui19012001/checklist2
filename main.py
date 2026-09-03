from __future__ import annotations

import json
import os
import sys
import ssl
import re
import threading
import traceback
from datetime import datetime, timedelta, timezone
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
        self.url = cfg.get("SUPABASE_URL", "").rstrip("/")
        self.anon = cfg.get("SUPABASE_ANON_KEY", "")

    @property
    def configured(self):
        return bool(self.url and self.anon)

    def rpc(self, name, payload=None, timeout=20):
        if not self.configured:
            raise RuntimeError(
                "SUPABASE_URL / SUPABASE_ANON_KEY não configurados em tablet.env."
            )

        body = json.dumps(
            dict(payload or {}), ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")

        req = Request(
            f"{self.url}/rest/v1/rpc/{name}",
            data=body,
            headers={
                "apikey": self.anon,
                "Authorization": f"Bearer {self.anon}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            ssl_context = None
            if self.url.lower().startswith("https://"):
                if certifi is not None:
                    ssl_context = ssl.create_default_context(cafile=certifi.where())
                else:
                    ssl_context = ssl.create_default_context()

            if ssl_context is not None:
                response = urlopen(req, timeout=timeout, context=ssl_context)
            else:
                response = urlopen(req, timeout=timeout)

            with response as resp:
                raw = resp.read().decode("utf-8")
                if not raw.strip():
                    return None
                return json.loads(raw)

        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {raw[:700]}") from exc
        except URLError as exc:
            reason = getattr(exc, "reason", exc)
            raise RuntimeError(f"Falha de conexão com o Supabase: {reason}") from exc
        except TimeoutError as exc:
            raise RuntimeError("Tempo esgotado ao comunicar com o Supabase.") from exc

    def machines(self):
        return self.rpc("aps_tablet_maquinas")

    def queue(self, machine):
        return self.rpc("aps_tablet_fila_serra", {"p_maquina": machine})

    def start(
        self,
        operation_id,
        machine,
        operator,
        setup,
        device_id,
        start_at=None,
        queue_reason=None,
        overtime=False,
    ):
        return self.rpc(
            "aps_tablet_iniciar_execucao_v2",
            {
                "p_operacao_id": int(operation_id),
                "p_maquina": machine,
                "p_operador": operator,
                "p_setup": bool(setup),
                "p_device_id": device_id,
                "p_inicio_em": start_at,
                "p_motivo_fora_fila": queue_reason or None,
                "p_hora_extra": bool(overtime),
            },
        )

    def finish_setup(self, execution_id):
        return self.rpc(
            "aps_tablet_finalizar_setup", {"p_execucao_id": execution_id}
        )

    def pause(self, execution_id):
        return self.rpc("aps_tablet_pausar", {"p_execucao_id": execution_id})

    def resume(self, execution_id):
        return self.rpc("aps_tablet_retomar", {"p_execucao_id": execution_id})

    def finish(
        self,
        execution_id,
        good,
        scrap,
        note,
        kind="PARCIAL",
        end_at=None,
        next_action=None,
    ):
        return self.rpc(
            "aps_tablet_finalizar_execucao_v2",
            {
                "p_execucao_id": execution_id,
                "p_quantidade_boa": float(good),
                "p_quantidade_refugo": float(scrap),
                "p_observacao": note or "",
                "p_tipo": kind,
                "p_fim_em": end_at,
                "p_proximo_passo": next_action,
            },
        )

    def partial_continue(self, execution_id, good, scrap, note, end_at=None):
        return self.rpc(
            "aps_tablet_parcial_continuar",
            {
                "p_execucao_id": execution_id,
                "p_quantidade_boa": float(good),
                "p_quantidade_refugo": float(scrap),
                "p_observacao": note or "",
                "p_fim_em": end_at,
            },
        )

    def overtime(self, execution_id, good, scrap, note):
        return self.rpc(
            "aps_tablet_virar_hora_extra",
            {
                "p_execucao_id": execution_id,
                "p_quantidade_boa": float(good),
                "p_quantidade_refugo": float(scrap),
                "p_observacao": note or "",
            },
        )

    def history(self, machine):
        return self.rpc(
            "aps_tablet_historico", {"p_maquina": machine, "p_limite": 80}
        )


# ============================================================
# REGRAS DE TURNO
# ============================================================

BR_TZ = timezone(timedelta(hours=-3))
T1_START = (6, 0)
T1_END = (15, 48)
T2_START = (16, 0)
T2_END = (1, 20)


def br_now():
    return datetime.now(BR_TZ)


def minutes_of_day(dt):
    return dt.hour * 60 + dt.minute


def shift_info(dt=None):
    dt = dt or br_now()
    m = minutes_of_day(dt)
    t1_start = 6 * 60
    t1_end = 15 * 60 + 48
    t2_start = 16 * 60
    t2_end = 1 * 60 + 20

    if t1_start <= m <= t1_end:
        return "T1", "06:00–15:48"
    if m >= t2_start or m <= t2_end:
        return "T2", "16:00–01:20"
    if t2_end < m < t1_start:
        return "HORA EXTRA", "após 01:20"
    return "TRANSIÇÃO", "15:48–16:00"


def is_overtime_window(dt=None):
    dt = dt or br_now()
    m = minutes_of_day(dt)
    return (1 * 60 + 20) < m < (6 * 60)


def parse_manual_datetime(date_text, time_text):
    raw = f"{date_text.strip()} {time_text.strip()}"
    dt = datetime.strptime(raw, "%d/%m/%Y %H:%M")
    return dt.replace(tzinfo=BR_TZ)


def parse_iso_datetime(value):
    if not value:
        return None
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=BR_TZ)
    return dt.astimezone(BR_TZ)


def compact_order_ref(value):
    """Compacta referências sintéticas como ITEM|2026-S35|2026-09-03|P100."""
    raw = str(value or "").strip()
    if not raw:
        return "SEM REFERÊNCIA"

    parts = [p.strip() for p in raw.split("|") if p.strip()]
    if len(parts) >= 2:
        week = next(
            (p.upper() for p in parts if re.fullmatch(r"\d{4}-S\d{1,2}", p.upper())),
            None,
        )
        date_part = next(
            (p for p in parts if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p)),
            None,
        )
        labels = []
        if week:
            labels.append(week.split("-", 1)[1])
        if date_part:
            try:
                labels.append(datetime.strptime(date_part, "%Y-%m-%d").strftime("%d/%m/%Y"))
            except Exception:
                labels.append(date_part)
        if labels:
            return " · ".join(labels)

    return f"OP {raw}"


def compact_plan_ref(plan):
    if not isinstance(plan, dict):
        return "Programação congelada"
    code = str(plan.get("codigo_plano") or "").strip()
    if not code:
        return "Programação congelada"
    compact = compact_order_ref(code)
    if compact.startswith("OP "):
        return "Programação congelada"
    return f"Programação · {compact}"


def safe_float(value, default=0.0):
    try:
        return float(value or default)
    except Exception:
        return float(default)


# ============================================================
# TELA OPERACIONAL 0.5.1
# ============================================================

class OperationScreen(Screen):
    ACTIVE_STATUSES = {"EM_SETUP", "EM SETUP", "EM_PRODUCAO", "EM PRODUCAO", "PAUSADA"}

    def __init__(self, **kw):
        super().__init__(**kw)
        self.busy = False
        self.orders = []
        self.plan = {}
        self.shift_prompt_exec_id = None
        self.shift_popup = None

        root = BoxLayout(
            orientation="vertical",
            padding=[dp(12), dp(8), dp(12), dp(10)],
            spacing=dp(8),
        )
        self.add_widget(root)

        self.header = BoxLayout(size_hint_y=None, height=dp(64))
        root.add_widget(self.header)

        self.identity = Card(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(66),
            padding=[dp(12), dp(7)],
            spacing=dp(8),
        )
        root.add_widget(self.identity)

        self.body = BoxLayout(orientation="horizontal", spacing=dp(9))
        root.add_widget(self.body)

        self.footer = BoxLayout(size_hint_y=None, height=dp(28))
        root.add_widget(self.footer)

        self.build_identity()
        self.render_header()
        self.render_footer()

        Clock.schedule_interval(self._tick, 1.0)
        Clock.schedule_interval(self.check_shift_boundary, 20.0)

    def on_pre_enter(self, *_):
        self.load_cached()
        Clock.schedule_once(lambda *_: self.refresh_remote(), .35)
        Clock.schedule_once(lambda *_: self.check_shift_boundary(), 1.5)

    # --------------------------------------------------------
    # CABEÇALHO / IDENTIDADE
    # --------------------------------------------------------

    def render_header(self):
        self.header.clear_widgets()
        app = App.get_running_app()

        c = Card(orientation="horizontal", padding=[dp(15), dp(7)], spacing=dp(8))
        left = BoxLayout(orientation="vertical", size_hint_x=.55)
        left.add_widget(lbl("APS SERRA · OPERAÇÃO", C_TEXT, sp(20), dp(30), True))
        plan_text = compact_plan_ref(self.plan)
        left.add_widget(lbl(plan_text, C_MUTED, sp(10), dp(20)))
        c.add_widget(left)

        middle = BoxLayout(orientation="vertical", size_hint_x=.25)
        self.clock_label = lbl("", C_TEXT, sp(18), dp(30), True)
        self.shift_label = lbl("", C_MUTED, sp(10), dp(20), True)
        middle.add_widget(self.clock_label)
        middle.add_widget(self.shift_label)
        c.add_widget(middle)

        c.add_widget(Status("ONLINE" if app.online else "OFFLINE", "OK" if app.online else "BAD"))
        self.header.add_widget(c)
        self._tick()

    def _tick(self, *_):
        now = br_now()
        turno, janela = shift_info(now)
        if hasattr(self, "clock_label"):
            self.clock_label.text = now.strftime("%d/%m · %H:%M:%S")
        if hasattr(self, "shift_label"):
            self.shift_label.text = f"{turno} · {janela}"
        self.render_footer()

    def render_footer(self):
        self.footer.clear_widgets()
        now = br_now()
        turno, _ = shift_info(now)
        text = (
            "T1 06:00–15:48   ·   T2 16:00–01:20   ·   "
            "Após 01:20: finalizar tarefa ou registrar hora extra"
        )
        tone = C_YELLOW if turno == "HORA EXTRA" else C_MUTED
        self.footer.add_widget(lbl(text, tone, sp(9), dp(24), turno == "HORA EXTRA"))

    def build_identity(self):
        self.identity.clear_widgets()
        app = App.get_running_app()

        opbox = BoxLayout(orientation="vertical", size_hint_x=.42, spacing=dp(1))
        opbox.add_widget(lbl("OPERADOR", C_MUTED, sp(9), dp(18), True))
        self.operator = Field(hint_text="Nome do operador")
        self.operator.text = app.store.data.get("config", {}).get("last_operator", "")
        opbox.add_widget(self.operator)

        mbox = BoxLayout(orientation="vertical", size_hint_x=.22, spacing=dp(1))
        mbox.add_widget(lbl("MÁQUINA", C_MUTED, sp(9), dp(18), True))
        self.machine = Spinner(
            text=app.store.data.get("config", {}).get("machine", "SER-01"),
            values=("SER-01", "SER-02", "SER-03", "SER-04", "SER-05"),
            background_normal="",
            background_color=C_DARK,
            color=C_TEXT,
            size_hint_y=None,
            height=dp(46),
            font_size=sp(14),
        )
        mbox.add_widget(self.machine)

        load_btn = FlatButton("ATUALIZAR FILA", bg=C_BLUE, size_hint_x=.20, height=dp(46))
        load_btn.bind(on_release=lambda *_: self.apply_identity())

        hist_btn = FlatButton("HISTÓRICO", bg=C_DARK, size_hint_x=.16, height=dp(46))
        hist_btn.bind(on_release=lambda *_: self.show_history_popup())

        self.identity.add_widget(opbox)
        self.identity.add_widget(mbox)
        self.identity.add_widget(load_btn)
        self.identity.add_widget(hist_btn)

    def operator_ok(self, show=True):
        name = self.operator.text.strip()
        if not name and show:
            self.popup("OPERADOR OBRIGATÓRIO", "Informe o nome do operador antes de executar qualquer ação.")
        return bool(name)

    def apply_identity(self):
        if not self.operator_ok():
            return
        app = App.get_running_app()
        try:
            app.operator = self.operator.text.strip()
            app.machine = self.machine.text
            app.store.data["config"] = {
                "machine": app.machine,
                "last_operator": app.operator,
            }
            app.store.save()
            self.refresh_remote()
        except Exception as e:
            app.online = False
            try:
                save_crash_report(traceback.format_exc(), app)
            except Exception:
                pass
            self.popup("ERRO AO CARREGAR FILA", str(e))

    # --------------------------------------------------------
    # DADOS / REFRESH
    # --------------------------------------------------------

    def load_cached(self):
        app = App.get_running_app()
        self.orders = app.store.data.get("orders", [])
        self.plan = app.store.data.get("plan", {}) or {}
        self.render_header()
        self.render_workspace()

    def refresh_remote(self):
        if self.busy:
            return
        if not self.operator_ok(False):
            self.render_workspace()
            return

        app = App.get_running_app()
        app.operator = self.operator.text.strip()
        app.machine = self.machine.text
        self.busy = True

        def work():
            try:
                data = app.api.queue(app.machine)
                if isinstance(data, dict):
                    rows = data.get("orders", []) or []
                    plan = data.get("plan", {}) or {}
                else:
                    rows, plan = data or [], {}

                Clock.schedule_once(
                    lambda *_args, rows=rows, plan=plan: self._refresh_ok(rows, plan), 0
                )
            except Exception as e:
                msg = str(e)
                trace = traceback.format_exc()
                try:
                    save_crash_report(trace, app)
                except Exception:
                    pass
                Clock.schedule_once(
                    lambda *_args, msg=msg: self._refresh_fail(msg), 0
                )

        threading.Thread(target=work, daemon=True).start()

    def _refresh_ok(self, rows, plan):
        app = App.get_running_app()
        self.busy = False
        app.online = True
        self.orders = rows
        self.plan = plan or {}
        app.store.data["orders"] = rows
        app.store.data["plan"] = self.plan
        app.store.save()
        self.render_header()
        self.render_workspace()
        Clock.schedule_once(lambda *_: self.check_shift_boundary(), .2)

    def _refresh_fail(self, msg):
        app = App.get_running_app()
        self.busy = False
        app.online = False
        self.render_header()
        try:
            app.store.event(f"Falha de comunicação: {msg}")
        except Exception:
            pass
        self.render_workspace()
        self.popup(
            "SEM COMUNICAÇÃO",
            f"Não foi possível atualizar o Supabase.\n\n{msg}\n\nA última fila salva permanece visível.",
        )

    # --------------------------------------------------------
    # FILA / ORDEM ATUAL
    # --------------------------------------------------------

    def status_upper(self, order):
        return str(order.get("status", "")).upper()

    def active_order(self):
        for order in self.orders:
            if self.status_upper(order) in self.ACTIVE_STATUSES and order.get("active_execution_id"):
                return order
        return None

    def current(self):
        active = self.active_order()
        if active:
            return active
        opened = [o for o in self.orders if self.status_upper(o) != "CONCLUIDA"]
        opened.sort(key=lambda o: int(o.get("seq", 999999) or 999999))
        return opened[0] if opened else None

    def first_pending(self):
        opened = [o for o in self.orders if self.status_upper(o) != "CONCLUIDA"]
        opened.sort(key=lambda o: int(o.get("seq", 999999) or 999999))
        return opened[0] if opened else None

    def tone(self, status):
        s = str(status).upper()
        if s in ("EM_PRODUCAO", "EM PRODUCAO", "EM_SETUP", "EM SETUP"):
            return "RUN"
        if s == "CONCLUIDA":
            return "OK"
        if s in ("PAUSADA", "PARCIAL"):
            return "WARN"
        if s == "BLOQUEADA":
            return "BAD"
        return "WAIT"

    def cell(self, title, value, accent=C_TEXT):
        c = Card(
            orientation="vertical",
            padding=[dp(9), dp(5)],
            spacing=0,
            radius=dp(10),
            bg_color=(.035, .075, .12, 1),
        )
        c.add_widget(lbl(title, C_MUTED, sp(8), dp(20), True))
        c.add_widget(lbl(value, accent, sp(15), dp(30), True))
        return c

    def render_workspace(self):
        self.body.clear_widgets()

        left = BoxLayout(orientation="vertical", size_hint_x=.72, spacing=dp(7))
        side = Card(
            orientation="vertical",
            size_hint_x=.28,
            padding=[dp(10), dp(9)],
            spacing=dp(6),
            bg_color=(.035, .07, .115, 1),
        )

        self.render_current(left)
        self.render_queue_side(side)
        self.body.add_widget(left)
        self.body.add_widget(side)

    def render_current(self, parent):
        app = App.get_running_app()
        if not self.operator.text.strip():
            c = Card(orientation="vertical", padding=dp(22))
            c.add_widget(lbl("IDENTIFIQUE O OPERADOR", C_TEXT, sp(24), dp(52), True))
            c.add_widget(lbl(
                "Informe o operador e a máquina. A fila aparecerá ao lado e a ordem atual ocupará a área principal.",
                C_MUTED, sp(13), dp(60)
            ))
            parent.add_widget(c)
            return

        o = self.current()
        if not o:
            c = Card(orientation="vertical", padding=dp(22))
            c.add_widget(lbl("FILA CONCLUÍDA", C_GREEN, sp(26), dp(58), True))
            c.add_widget(lbl(f"Nenhuma ordem aberta para {app.machine}.", C_MUTED, sp(13), dp(38)))
            parent.add_widget(c)
            return

        c = Card(orientation="vertical", padding=dp(16), spacing=dp(8))

        top = BoxLayout(size_hint_y=None, height=dp(70), spacing=dp(8))
        info = BoxLayout(orientation="vertical")
        info.add_widget(lbl(f'OP {o.get("op", "")}', C_TEXT, sp(24), dp(36), True))
        desc = f'{o.get("item", "")} · {o.get("description", "")}'
        info.add_widget(lbl(desc, C_MUTED, sp(11), dp(28)))
        top.add_widget(info)
        top.add_widget(Status(str(o.get("status", "AGUARDANDO")), self.tone(o.get("status"))))
        c.add_widget(top)

        planned = safe_float(o.get("planned_qty"))
        done = safe_float(o.get("done_qty"))
        saldo = max(0.0, planned - done)

        metrics = GridLayout(cols=4, size_hint_y=None, height=dp(70), spacing=dp(7))
        metrics.add_widget(self.cell("SEQUÊNCIA", f'{int(o.get("seq", 0) or 0):02d}', C_BLUE))
        metrics.add_widget(self.cell("PROGRAMADO", f"{planned:g} pç"))
        metrics.add_widget(self.cell("REALIZADO", f"{done:g} pç", C_GREEN))
        metrics.add_widget(self.cell("SALDO", f"{saldo:g} pç", C_YELLOW if saldo else C_GREEN))
        c.add_widget(metrics)
        c.add_widget(Progress(value=100 * done / max(1, planned)))

        exec_meta = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(7))
        active_start = hhmm(o.get("active_inicio_em")) if o.get("active_execution_id") else "--:--"
        turno = str(o.get("active_turno") or "-")
        operador = str(o.get("active_operador") or app.operator or "-")
        he = " · HORA EXTRA" if o.get("active_hora_extra") else ""
        exec_meta.add_widget(lbl(f"INÍCIO: {active_start}", C_MUTED, sp(10), dp(38), True))
        exec_meta.add_widget(lbl(f"TURNO: {turno}{he}", C_MUTED, sp(10), dp(38), True))
        exec_meta.add_widget(lbl(f"OPERADOR: {operador}", C_MUTED, sp(10), dp(38), True))
        c.add_widget(exec_meta)

        actions = BoxLayout(size_hint_y=None, height=dp(58), spacing=dp(8))
        s = self.status_upper(o)

        if s in ("AGUARDANDO", "PARCIAL"):
            b = FlatButton("INICIAR", bg=C_BLUE, height=dp(56))
            b.bind(on_release=lambda *_: self.open_start_dialog(o, require_reason=False))
            actions.add_widget(b)

        elif s in ("EM_SETUP", "EM SETUP"):
            b = FlatButton("FINALIZAR SETUP", bg=C_YELLOW, fg=(.04, .05, .07, 1), height=dp(56))
            b.bind(on_release=lambda *_: self.command("setup", o))
            actions.add_widget(b)

        elif s in ("EM_PRODUCAO", "EM PRODUCAO"):
            partial = FlatButton("APONTAR PARCIAL", bg=C_BLUE, height=dp(56))
            partial.bind(on_release=lambda *_: self.open_quantity_dialog(o, "PARCIAL"))
            pause = FlatButton("PAUSAR", bg=C_DARK, height=dp(56))
            pause.bind(on_release=lambda *_: self.command("pause", o))
            finish = FlatButton("CONCLUIR OP", bg=C_GREEN, height=dp(56))
            finish.bind(on_release=lambda *_: self.open_quantity_dialog(o, "CONCLUSAO"))
            actions.add_widget(partial)
            actions.add_widget(pause)
            actions.add_widget(finish)

        elif s == "PAUSADA":
            partial = FlatButton("APONTAR PARCIAL", bg=C_BLUE, height=dp(56))
            partial.bind(on_release=lambda *_: self.open_quantity_dialog(o, "PARCIAL"))
            resume = FlatButton("RETOMAR", bg=C_YELLOW, fg=(.04, .05, .07, 1), height=dp(56))
            resume.bind(on_release=lambda *_: self.command("resume", o))
            finish = FlatButton("CONCLUIR OP", bg=C_GREEN, height=dp(56))
            finish.bind(on_release=lambda *_: self.open_quantity_dialog(o, "CONCLUSAO"))
            actions.add_widget(partial)
            actions.add_widget(resume)
            actions.add_widget(finish)

        c.add_widget(actions)
        parent.add_widget(c)

    def render_queue_side(self, side):
        side.add_widget(lbl("PRÓXIMOS DA FILA", C_TEXT, sp(13), dp(30), True))
        side.add_widget(lbl("Toque em ESCOLHER para mudar a sequência.", C_MUTED, sp(9), dp(28)))

        current = self.current()
        current_id = current.get("operation_id") if current else None
        rows = [o for o in self.orders if self.status_upper(o) != "CONCLUIDA" and o.get("operation_id") != current_id]
        rows.sort(key=lambda o: int(o.get("seq", 999999) or 999999))

        sc = ScrollView(do_scroll_x=False)
        stack = GridLayout(cols=1, spacing=dp(6), size_hint_y=None)
        stack.bind(minimum_height=stack.setter("height"))

        if not rows:
            stack.add_widget(lbl("Sem próximos itens.", C_MUTED, sp(11), dp(52)))

        for o in rows[:8]:
            planned = safe_float(o.get("planned_qty"))
            done = safe_float(o.get("done_qty"))
            saldo = max(0, planned - done)

            card = Card(
                orientation="vertical",
                size_hint_y=None,
                height=dp(118),
                padding=[dp(8), dp(6)],
                spacing=dp(2),
                radius=dp(10),
                bg_color=(.045, .085, .135, 1),
            )
            row1 = BoxLayout(size_hint_y=None, height=dp(27))
            queue_ref = compact_order_ref(o.get("op", ""))
            row1.add_widget(lbl(
                f'#{int(o.get("seq", 0) or 0):02d} · {queue_ref}',
                C_TEXT, sp(10), dp(25), True
            ))
            row1.add_widget(Status(str(o.get("status", "")), self.tone(o.get("status"))))
            card.add_widget(row1)
            card.add_widget(lbl(str(o.get("item", "")), C_BLUE, sp(10), dp(22), True))
            card.add_widget(lbl(f"Saldo {saldo:g} pç", C_MUTED, sp(9), dp(20)))
            choose = FlatButton("ESCOLHER", bg=C_DARK, height=dp(34))
            choose.bind(on_release=lambda *_args, order=o: self.select_queue_order(order))
            card.add_widget(choose)
            stack.add_widget(card)

        sc.add_widget(stack)
        side.add_widget(sc)

    # --------------------------------------------------------
    # INICIAR / TROCAR FILA
    # --------------------------------------------------------

    def select_queue_order(self, order):
        if not self.operator_ok():
            return

        active = self.active_order()
        if active and active.get("operation_id") != order.get("operation_id"):
            self.open_switch_reason(active, order)
            return

        first = self.first_pending()
        require_reason = bool(first and first.get("operation_id") != order.get("operation_id"))
        self.open_start_dialog(order, require_reason=require_reason)

    def reason_widgets(self):
        reason = Spinner(
            text="SELECIONE O MOTIVO",
            values=(
                "PRIORIDADE PCP",
                "FALTA DE MATERIAL",
                "SETUP / OTIMIZAÇÃO",
                "MANUTENÇÃO / BLOQUEIO",
                "QUALIDADE",
                "OUTRO",
            ),
            background_normal="",
            background_color=C_DARK,
            color=C_TEXT,
            size_hint_y=None,
            height=dp(46),
        )
        detail = Field(hint_text="Detalhe / justificativa")
        return reason, detail

    def compose_reason(self, reason, detail):
        base = reason.text.strip()
        extra = detail.text.strip()
        if base == "SELECIONE O MOTIVO":
            return ""
        return f"{base} · {extra}" if extra else base

    def open_switch_reason(self, current_order, target_order):
        box = BoxLayout(orientation="vertical", padding=dp(18), spacing=dp(8))
        box.add_widget(lbl("TROCAR ORDEM DA FILA", C_TEXT, sp(20), dp(38), True))
        box.add_widget(lbl(
            f'Atual: OP {current_order.get("op", "")}  →  Selecionada: OP {target_order.get("op", "")}',
            C_MUTED, sp(11), dp(35)
        ))
        box.add_widget(lbl(
            "Para trocar uma ordem ativa, o apontamento produzido até agora será registrado como parcial.",
            C_YELLOW, sp(11), dp(48), True
        ))
        reason, detail = self.reason_widgets()
        box.add_widget(reason)
        box.add_widget(detail)
        msg = lbl("", C_RED, sp(10), dp(24), True)
        box.add_widget(msg)
        row = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(8))
        back = FlatButton("CANCELAR")
        go = FlatButton("APONTAR E TROCAR", bg=C_BLUE)
        row.add_widget(back)
        row.add_widget(go)
        box.add_widget(row)
        pop = Popup(title="", content=box, size_hint=(.78, .80), separator_height=0)
        back.bind(on_release=lambda *_: pop.dismiss())

        def continue_switch(*_):
            queue_reason = self.compose_reason(reason, detail)
            if not queue_reason:
                msg.text = "Justificativa obrigatória para mudar a sequência."
                return
            pop.dismiss()
            self.open_quantity_dialog(
                current_order,
                "TROCA_FILA",
                after_success=lambda: self.open_start_dialog(
                    target_order, require_reason=False, forced_reason=queue_reason
                ),
                note_prefix=f"Troca de fila: {queue_reason}",
            )

        go.bind(on_release=continue_switch)
        pop.open()

    def open_start_dialog(self, order, require_reason=False, forced_reason=None):
        if self.active_order() and self.active_order().get("operation_id") != order.get("operation_id"):
            self.popup("EXECUÇÃO ATIVA", "Existe outra ordem em execução. Faça um apontamento parcial antes de trocar.")
            return

        box = BoxLayout(orientation="vertical", padding=dp(17), spacing=dp(7))
        box.add_widget(lbl("INICIAR ORDEM", C_TEXT, sp(20), dp(38), True))
        box.add_widget(lbl(
            f'OP {order.get("op", "")} · {order.get("item", "")}',
            C_BLUE, sp(13), dp(31), True
        ))

        setup = Spinner(
            text="SEM SETUP",
            values=("SEM SETUP", "COM SETUP"),
            background_normal="",
            background_color=C_DARK,
            color=C_TEXT,
            size_hint_y=None,
            height=dp(45),
        )
        box.add_widget(lbl("SETUP", C_MUTED, sp(9), dp(18), True))
        box.add_widget(setup)

        mode = Spinner(
            text="AGORA",
            values=("AGORA", "MANUAL"),
            background_normal="",
            background_color=C_DARK,
            color=C_TEXT,
            size_hint_y=None,
            height=dp(45),
        )
        box.add_widget(lbl("HORA DE INÍCIO", C_MUTED, sp(9), dp(18), True))
        box.add_widget(mode)

        dtrow = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(7))
        now = br_now()
        date_field = Field(text=now.strftime("%d/%m/%Y"), hint_text="DD/MM/AAAA")
        time_field = Field(text=now.strftime("%H:%M"), hint_text="HH:MM")
        date_field.disabled = True
        time_field.disabled = True
        dtrow.add_widget(date_field)
        dtrow.add_widget(time_field)
        box.add_widget(dtrow)

        shift_preview = lbl("", C_YELLOW, sp(10), dp(28), True)
        box.add_widget(shift_preview)

        def update_shift_preview(*_):
            try:
                preview_dt = (
                    br_now()
                    if mode.text == "AGORA"
                    else parse_manual_datetime(date_field.text, time_field.text)
                )
                preview_shift, preview_window = shift_info(preview_dt)
                shift_preview.text = (
                    f"TURNO DESTA EXECUÇÃO: {preview_shift} · {preview_window}"
                )
            except Exception:
                shift_preview.text = "TURNO: revise a data/hora informada"

        def mode_changed(_spinner, value):
            manual = value == "MANUAL"
            date_field.disabled = not manual
            time_field.disabled = not manual
            update_shift_preview()

        mode.bind(text=mode_changed)
        date_field.bind(text=update_shift_preview)
        time_field.bind(text=update_shift_preview)
        update_shift_preview()

        reason = detail = None
        if forced_reason:
            box.add_widget(lbl("JUSTIFICATIVA DA TROCA", C_MUTED, sp(9), dp(18), True))
            box.add_widget(lbl(forced_reason, C_YELLOW, sp(10), dp(38), True))
        elif require_reason:
            box.add_widget(lbl("JUSTIFICATIVA PARA FURAR FILA", C_MUTED, sp(9), dp(18), True))
            reason, detail = self.reason_widgets()
            box.add_widget(reason)
            box.add_widget(detail)

        msg = lbl("", C_RED, sp(10), dp(24), True)
        box.add_widget(msg)
        row = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(8))
        back = FlatButton("VOLTAR")
        start_btn = FlatButton("INICIAR", bg=C_GREEN)
        row.add_widget(back)
        row.add_widget(start_btn)
        box.add_widget(row)
        pop = Popup(title="", content=box, size_hint=(.80, .93), separator_height=0)
        back.bind(on_release=lambda *_: pop.dismiss())

        def confirm(*_):
            queue_reason = forced_reason
            if require_reason and not forced_reason:
                queue_reason = self.compose_reason(reason, detail)
                if not queue_reason:
                    msg.text = "Informe o motivo para mudar a sequência."
                    return

            start_at = None
            check_dt = br_now()
            if mode.text == "MANUAL":
                try:
                    manual_dt = parse_manual_datetime(date_field.text, time_field.text)
                except Exception:
                    msg.text = "Data/hora inválida. Use DD/MM/AAAA e HH:MM."
                    return
                if manual_dt > br_now() + timedelta(minutes=5):
                    msg.text = "A hora de início não pode estar no futuro."
                    return
                start_at = manual_dt.isoformat()
                check_dt = manual_dt

            overtime = is_overtime_window(check_dt)
            try:
                app = App.get_running_app()
                res = app.api.start(
                    order["operation_id"],
                    app.machine,
                    self.operator.text.strip(),
                    setup.text == "COM SETUP",
                    app.device_id,
                    start_at=start_at,
                    queue_reason=queue_reason,
                    overtime=overtime,
                )
                app.online = True
                origin = "manual" if start_at else "agora"
                app.store.event(f'OP {order.get("op")}: início {origin} confirmado.')
                pop.dismiss()
                self.refresh_remote()
            except Exception as e:
                msg.text = str(e)[:220]

        start_btn.bind(on_release=confirm)
        pop.open()

    # --------------------------------------------------------
    # APONTAMENTO / CONCLUSÃO
    # --------------------------------------------------------

    def open_quantity_dialog(self, order, kind, after_success=None, note_prefix=""):
        exec_id = order.get("active_execution_id")
        if not exec_id:
            self.popup("SEM EXECUÇÃO", "Não foi encontrada execução ativa para esta ordem.")
            return

        planned = safe_float(order.get("planned_qty"))
        done = safe_float(order.get("done_qty"))
        balance = max(0, planned - done)

        titles = {
            "PARCIAL": "APONTAMENTO PARCIAL",
            "CONCLUSAO": "CONCLUIR ORDEM",
            "TROCA_FILA": "APONTAR ANTES DE TROCAR",
            "VIRADA_TURNO": "FINALIZAR TAREFA / TURNO",
        }
        title = titles.get(kind, "APONTAMENTO")

        box = BoxLayout(orientation="vertical", padding=dp(15), spacing=dp(6))
        box.add_widget(lbl(title, C_TEXT, sp(20), dp(36), True))
        box.add_widget(lbl(
            f'OP {order.get("op", "")} · saldo atual {balance:g} pç',
            C_MUTED, sp(10), dp(28)
        ))

        g = GridLayout(cols=2, size_hint_y=None, height=dp(90), spacing=dp(7))
        a = BoxLayout(orientation="vertical")
        b = BoxLayout(orientation="vertical")
        a.add_widget(lbl("QUANTIDADE BOA", C_MUTED, sp(9), dp(19), True))
        default_qty = f"{balance:g}" if kind == "CONCLUSAO" else ""
        qty = Field(text=default_qty, hint_text="Quantidade", input_filter="float")
        a.add_widget(qty)
        b.add_widget(lbl("REFUGO", C_MUTED, sp(9), dp(19), True))
        scrap = Field(text="0", input_filter="float")
        b.add_widget(scrap)
        g.add_widget(a)
        g.add_widget(b)
        box.add_widget(g)

        # O fim pertence a ESTA execução, e não à OP inteira.
        end_mode = Spinner(
            text="AGORA",
            values=("AGORA", "MANUAL"),
            background_normal="",
            background_color=C_DARK,
            color=C_TEXT,
            size_hint_y=None,
            height=dp(42),
        )
        box.add_widget(lbl("HORA DE FIM DESTE TRECHO", C_MUTED, sp(9), dp(18), True))
        box.add_widget(end_mode)

        end_row = BoxLayout(size_hint_y=None, height=dp(45), spacing=dp(7))
        now = br_now()
        end_date = Field(text=now.strftime("%d/%m/%Y"), hint_text="DD/MM/AAAA")
        end_time = Field(text=now.strftime("%H:%M"), hint_text="HH:MM")
        end_date.disabled = True
        end_time.disabled = True
        end_row.add_widget(end_date)
        end_row.add_widget(end_time)
        box.add_widget(end_row)

        def end_mode_changed(_spinner, value):
            manual = value == "MANUAL"
            end_date.disabled = not manual
            end_time.disabled = not manual

        end_mode.bind(text=end_mode_changed)

        partial_action = None
        if kind == "PARCIAL":
            box.add_widget(lbl("APÓS ESTE APONTAMENTO", C_MUTED, sp(9), dp(18), True))
            partial_action = Spinner(
                text="CONTINUAR NESTA PEÇA",
                values=("CONTINUAR NESTA PEÇA", "IR PARA OUTRA PEÇA"),
                background_normal="",
                background_color=C_DARK,
                color=C_TEXT,
                size_hint_y=None,
                height=dp(42),
            )
            box.add_widget(partial_action)

        note = Field(hint_text="Observação opcional")
        if note_prefix:
            note.text = note_prefix
        box.add_widget(note)

        if kind == "PARCIAL":
            box.add_widget(lbl(
                "CONTINUAR: salva este trecho e abre uma nova execução a partir do horário de fim. "
                "IR PARA OUTRA: encerra o trecho e deixa a OP PARCIAL na fila.",
                C_YELLOW, sp(9), dp(48), True
            ))
        elif kind in ("TROCA_FILA", "VIRADA_TURNO"):
            box.add_widget(lbl(
                "A ordem continuará na fila como PARCIAL se ainda existir saldo.",
                C_YELLOW, sp(9), dp(30), True
            ))

        msg = lbl("", C_RED, sp(9), dp(22), True)
        box.add_widget(msg)
        row = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(8))
        back = FlatButton("VOLTAR")
        ok = FlatButton("CONFIRMAR", bg=C_GREEN)
        row.add_widget(back)
        row.add_widget(ok)
        box.add_widget(row)
        pop = Popup(title="", content=box, size_hint=(.78, .94), separator_height=0)
        back.bind(on_release=lambda *_: pop.dismiss())

        def confirm(*_):
            try:
                q = float(qty.text.replace(",", "."))
                r = float(scrap.text.replace(",", "."))
            except Exception:
                msg.text = "Quantidades inválidas."
                return

            if q <= 0 or r < 0:
                msg.text = "Quantidade boa deve ser maior que zero e refugo não pode ser negativo."
                return

            end_at = None
            end_dt = br_now()
            if end_mode.text == "MANUAL":
                try:
                    end_dt = parse_manual_datetime(end_date.text, end_time.text)
                except Exception:
                    msg.text = "Fim inválido. Use DD/MM/AAAA e HH:MM."
                    return

                if end_dt > br_now() + timedelta(minutes=5):
                    msg.text = "A hora de fim não pode estar no futuro."
                    return
                end_at = end_dt.isoformat()

            active_start = parse_iso_datetime(order.get("active_inicio_em"))
            if active_start and end_dt < active_start:
                msg.text = (
                    f"O fim não pode ser anterior ao início desta execução "
                    f"({active_start:%d/%m %H:%M})."
                )
                return

            if kind == "PARCIAL":
                next_action = (
                    "CONTINUAR"
                    if partial_action.text == "CONTINUAR NESTA PEÇA"
                    else "TROCAR_PECA"
                )
            elif kind == "TROCA_FILA":
                next_action = "TROCAR_PECA"
            elif kind == "CONCLUSAO":
                next_action = "CONCLUIR"
            else:
                next_action = "ENCERRAR"

            try:
                app = App.get_running_app()

                # CONTINUAR é atômico no Supabase:
                # fecha este período e cria outra execução da mesma OP
                # começando exatamente no fim informado.
                if kind == "PARCIAL" and next_action == "CONTINUAR":
                    res = app.api.partial_continue(
                        exec_id,
                        q,
                        r,
                        note.text.strip(),
                        end_at=end_at,
                    )
                    order_status = (
                        (res or {}).get("order_status", "")
                        if isinstance(res, dict)
                        else ""
                    )
                    app.store.event(
                        f'OP {order.get("op")}: {q:g} pç parciais · continuidade aberta.'
                    )
                    pop.dismiss()
                    self.refresh_remote()
                    Clock.schedule_once(
                        lambda *_: self.popup(
                            "PARCIAL SALVO",
                            "Este trecho foi encerrado e uma nova execução da mesma peça foi iniciada "
                            "a partir do horário de fim informado.",
                        ),
                        .35,
                    )
                    return

                res = app.api.finish(
                    exec_id,
                    q,
                    r,
                    note.text.strip(),
                    kind=kind,
                    end_at=end_at,
                    next_action=next_action,
                )
                order_status = (
                    (res or {}).get("order_status", "")
                    if isinstance(res, dict)
                    else ""
                )
                app.store.event(
                    f'OP {order.get("op")}: {q:g} pç lançadas · {kind} · {next_action}.'
                )
                pop.dismiss()
                self.refresh_remote()

                if after_success:
                    Clock.schedule_once(lambda *_: after_success(), .65)
                elif kind == "PARCIAL" and next_action == "TROCAR_PECA":
                    Clock.schedule_once(
                        lambda *_: self.popup(
                            "TRECHO ENCERRADO",
                            "A OP ficou PARCIAL na fila. Ao ser retomada, uma nova execução deverá "
                            "informar seu próprio horário de início e fim.",
                        ),
                        .35,
                    )
                elif order_status:
                    Clock.schedule_once(
                        lambda *_: self.popup(
                            "APONTAMENTO SALVO",
                            f"Situação da ordem: {order_status}",
                        ),
                        .35,
                    )
            except Exception as e:
                msg.text = str(e)[:260]

        ok.bind(on_release=confirm)
        pop.open()

    def command(self, kind, order):
        app = App.get_running_app()
        exec_id = order.get("active_execution_id")
        if not exec_id:
            self.popup("SEM EXECUÇÃO", "Não foi encontrada execução ativa no Supabase.")
            return
        try:
            {"setup": app.api.finish_setup, "pause": app.api.pause, "resume": app.api.resume}[kind](exec_id)
            app.store.event(f'OP {order.get("op")}: comando {kind} confirmado.')
            self.refresh_remote()
        except Exception as e:
            self.popup("ERRO DE COMUNICAÇÃO", str(e))

    # --------------------------------------------------------
    # VIRADA 01:20 / HORA EXTRA
    # --------------------------------------------------------

    def check_shift_boundary(self, *_):
        if not is_overtime_window():
            self.shift_prompt_exec_id = None
            return

        order = self.active_order()
        if not order:
            return

        exec_id = order.get("active_execution_id")
        if not exec_id or order.get("active_hora_extra"):
            return

        s = self.status_upper(order)
        if s in ("EM_SETUP", "EM SETUP"):
            if self.shift_prompt_exec_id != exec_id:
                self.shift_prompt_exec_id = exec_id
                self.popup(
                    "01:20 · FIM DO T2",
                    "A ordem ainda está em SETUP. Finalize o setup antes de seguir em hora extra.",
                )
            return

        if s not in ("EM_PRODUCAO", "EM PRODUCAO", "PAUSADA"):
            return

        if self.shift_prompt_exec_id == exec_id:
            return
        self.shift_prompt_exec_id = exec_id
        self.open_shift_choice(order)

    def open_shift_choice(self, order):
        box = BoxLayout(orientation="vertical", padding=dp(22), spacing=dp(12))
        box.add_widget(lbl("01:20 · FIM DO TURNO T2", C_YELLOW, sp(23), dp(46), True))
        box.add_widget(lbl(
            f'OP {order.get("op", "")} continua aberta.',
            C_TEXT, sp(15), dp(36), True
        ))
        box.add_widget(lbl(
            "Escolha obrigatoriamente uma ação. Se houver hora extra, primeiro será lançado tudo o que foi produzido até 01:20 e uma nova execução de HORA EXTRA será aberta a partir de 01:20.",
            C_MUTED, sp(12), dp(92)
        ))
        row = BoxLayout(size_hint_y=None, height=dp(64), spacing=dp(10))
        finish = FlatButton("FINALIZAR TAREFA?", bg=C_BLUE, height=dp(62))
        overtime = FlatButton("HORA EXTRA", bg=C_YELLOW, fg=(.04, .05, .07, 1), height=dp(62))
        row.add_widget(finish)
        row.add_widget(overtime)
        box.add_widget(row)

        pop = Popup(
            title="", content=box, size_hint=(.78, .62), separator_height=0, auto_dismiss=False
        )
        self.shift_popup = pop

        def finalize(*_):
            pop.dismiss()
            self.shift_popup = None
            self.open_quantity_dialog(order, "VIRADA_TURNO")

        def extra(*_):
            pop.dismiss()
            self.shift_popup = None
            self.open_overtime_dialog(order)

        finish.bind(on_release=finalize)
        overtime.bind(on_release=extra)
        pop.open()

    def open_overtime_dialog(self, order):
        exec_id = order.get("active_execution_id")
        box = BoxLayout(orientation="vertical", padding=dp(18), spacing=dp(8))
        box.add_widget(lbl("LANÇAR ATÉ 01:20 E SEGUIR EM HORA EXTRA", C_TEXT, sp(18), dp(44), True))
        box.add_widget(lbl(
            "O lançamento até 01:20 é obrigatório para abrir a continuação em HORA EXTRA.",
            C_YELLOW, sp(11), dp(44), True
        ))

        g = GridLayout(cols=2, size_hint_y=None, height=dp(94), spacing=dp(8))
        a = BoxLayout(orientation="vertical")
        b = BoxLayout(orientation="vertical")
        a.add_widget(lbl("BOAS ATÉ 01:20", C_MUTED, sp(9), dp(20), True))
        qty = Field(hint_text="Quantidade", input_filter="float")
        a.add_widget(qty)
        b.add_widget(lbl("REFUGO ATÉ 01:20", C_MUTED, sp(9), dp(20), True))
        scrap = Field(text="0", input_filter="float")
        b.add_widget(scrap)
        g.add_widget(a)
        g.add_widget(b)
        box.add_widget(g)
        note = Field(hint_text="Observação opcional")
        box.add_widget(note)
        msg = lbl("", C_RED, sp(10), dp(24), True)
        box.add_widget(msg)
        row = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(8))
        back = FlatButton("VOLTAR")
        ok = FlatButton("LANÇAR E INICIAR HORA EXTRA", bg=C_GREEN)
        row.add_widget(back)
        row.add_widget(ok)
        box.add_widget(row)
        pop = Popup(title="", content=box, size_hint=(.82, .78), separator_height=0, auto_dismiss=False)

        def back_action(*_):
            pop.dismiss()
            self.shift_prompt_exec_id = None
            Clock.schedule_once(lambda *_: self.check_shift_boundary(), .2)

        back.bind(on_release=back_action)

        def confirm(*_):
            try:
                q = float(qty.text.replace(",", "."))
                r = float(scrap.text.replace(",", "."))
            except Exception:
                msg.text = "Quantidades inválidas."
                return
            if q <= 0:
                msg.text = "Para seguir em hora extra é obrigatório lançar quantidade produzida até 01:20."
                return
            if r < 0:
                msg.text = "Refugo não pode ser negativo."
                return
            try:
                app = App.get_running_app()
                res = app.api.overtime(exec_id, q, r, note.text.strip())
                new_id = (res or {}).get("execution_id") if isinstance(res, dict) else None
                app.store.event(
                    f'OP {order.get("op")}: virada 01:20 registrada; hora extra iniciada.'
                )
                pop.dismiss()
                self.shift_prompt_exec_id = new_id
                self.refresh_remote()
            except Exception as e:
                msg.text = str(e)[:240]

        ok.bind(on_release=confirm)
        pop.open()

    # --------------------------------------------------------
    # HISTÓRICO / POPUP
    # --------------------------------------------------------

    def show_history_popup(self):
        app = App.get_running_app()
        box = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(7))
        box.add_widget(lbl("HISTÓRICO DA MÁQUINA", C_TEXT, sp(20), dp(38), True))
        sc = ScrollView(do_scroll_x=False)
        stack = GridLayout(cols=1, spacing=dp(6), size_hint_y=None)
        stack.bind(minimum_height=stack.setter("height"))

        try:
            rows = app.api.history(self.machine.text) or []
        except Exception as e:
            rows = []
            stack.add_widget(lbl(f"Falha ao carregar histórico: {e}", C_RED, sp(10), dp(60)))

        for e in rows[:80]:
            start = hhmm(e.get("inicio_em"))
            end = hhmm(e.get("fim_em"))
            turno = e.get("turno") or "-"
            extra = " · HE" if e.get("hora_extra") else ""
            qty = safe_float(e.get("quantidade_boa"))
            text = f'{start}–{end} · {turno}{extra} · OP {e.get("op", "")} · {qty:g} pç · {e.get("operador", "")}'
            card = Card(orientation="vertical", size_hint_y=None, height=dp(58), padding=[dp(9), dp(5)])
            card.add_widget(lbl(text, C_TEXT, sp(10), dp(28), True))
            if e.get("motivo_fora_fila"):
                card.add_widget(lbl(f'Motivo: {e.get("motivo_fora_fila")}', C_MUTED, sp(8), dp(20)))
            stack.add_widget(card)

        sc.add_widget(stack)
        box.add_widget(sc)
        close = FlatButton("FECHAR", bg=C_BLUE, height=dp(46))
        box.add_widget(close)
        pop = Popup(title="", content=box, size_hint=(.93, .90), separator_height=0)
        close.bind(on_release=lambda *_: pop.dismiss())
        pop.open()

    def popup(self, title, text):
        box = BoxLayout(orientation="vertical", padding=dp(20), spacing=dp(12))
        box.add_widget(lbl(title, C_TEXT, sp(20), dp(42), True))
        box.add_widget(lbl(text, C_MUTED, sp(12), dp(120)))
        b = FlatButton("OK", bg=C_BLUE)
        box.add_widget(b)
        p = Popup(title="", content=box, size_hint=(.72, .58), separator_height=0)
        b.bind(on_release=lambda *_: p.dismiss())
        p.open()


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

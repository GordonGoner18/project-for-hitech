"""НЕРЕЙ — учебный пульт НПА. Запуск: .venv\\Scripts\\python.exe main.py."""
from __future__ import annotations
from collections import deque
from datetime import datetime
import json
import math
from pathlib import Path
import time
import tkinter as tk
from tkinter import ttk
from model import InputGate, Vehicle
from recording import SessionRecorder
from scene import HEIGHT, WIDTH, ppm, render

BG, PANEL, EDGE = '#0a111d', '#111e2e', '#25384c'
TEXT, MUTED, CYAN, RED, AMBER = '#e8f0f7', '#8ea5ba', '#48dcca', '#ff7185', '#f4bf67'
OUTPUT = Path(__file__).resolve().parent / 'captures'
LESSONS = [
    ('Связь с аппаратом', 'Нажмите «Подключить» вверху окна. Появятся изображение камеры и показания датчиков.', 'connected', 'connection'),
    ('Первый манёвр', 'Удерживайте W или кнопку «Вперёд», затем отпустите. A/D меняют курс, Q/E — глубину.', 'moved', 'controls'),
    ('Обычная остановка', 'Нажмите Space или «Стоп движения». Удерживаемые клавиши после стопа нужно отпустить перед новой командой.', 'stopped', 'safety'),
    ('Удержание глубины', 'В поле справа задано 122 м. Нажмите «Удерживать» и дождитесь достижения глубины. Ручная команда Q/E отменяет удержание.', 'depth', 'depth'),
    ('Снимок наблюдения', 'Нажмите «Снимок PNG» под камерой. В captures сохранятся изображение и JSON с показаниями в момент снимка.', 'photo', 'camera'),
    ('Запись сеанса', 'Включите «Запись AVI + CSV», подождите несколько секунд и завершите запись той же кнопкой.', 'recorded', 'camera'),
    ('Аварийная остановка', 'Нажмите Esc или красную кнопку «Аварийный стоп». Движение и удержание глубины будут заблокированы.', 'emergency', 'safety'),
    ('Возврат к работе', 'Нажмите «Сброс аварии». Аппарат останется неподвижным до новой команды. Затем завершите обучение.', 'reset', 'safety'),
]

class Console(tk.Tk):
    def __init__(self):
        # Windows: ?????????? ???? ? ??????? ??????????? ? ????????? ??????.
        import sys
        if sys.platform == 'win32':
            import ctypes
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except (AttributeError, OSError):
                pass
        super().__init__()
        self.tk.call('tk', 'scaling', 4 / 3)
        self.title('НЕРЕЙ · Учебный пульт подводного аппарата')
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f'{min(1400, sw - 60)}x{min(920, sh - 90)}')
        self.minsize(min(980, sw - 40), min(650, sh - 90))
        self.configure(bg=BG)
        self.vehicle, self.inputs = Vehicle(), InputGate()
        self.recorder = None
        self.record_started = self.last_frame = 0.0
        self.frame_rgb = self.frame_image = None
        self.after_id = self.focus_job = None
        self.closed = False
        self.last_tick = self.clock_started = time.monotonic()
        self.log_lines = deque(maxlen=1000)
        self.events = {}
        self.lesson = None
        self.lesson_baseline = 0
        self.lesson_done = False
        self.highlighted = None
        self.alert_previous = ''
        self.limit, self.light = tk.DoubleVar(value=.5), tk.DoubleVar(value=65)
        self.target = tk.StringVar(value='122')
        self.limit_label, self.light_label = tk.StringVar(), tk.StringVar()
        self.notice = tk.StringVar(value='Готово к работе. Подключите симулятор или начните обучение.')
        self.status, self.alarm = tk.StringVar(), tk.StringVar()
        self.record_status = tk.StringVar(value='КАМЕРА 01 / SIM')
        self.metrics, self.metric_widgets, self.panels, self.movement_buttons = {}, {}, {}, {}
        self.compact_details = []
        self.compact = None
        self.setup_style()
        self.build()
        self.bind('<Configure>', self.resize_layout, add='+')
        self.install_key_bindings(self)
        self.bind_class('PilotKeys', '<KeyPress>', self.key_press)
        self.bind_class('PilotKeys', '<KeyRelease>', self.key_release)
        self.bind('<ButtonRelease-1>', self.mouse_release, add='+')
        self.bind('<FocusOut>', self.focus_out, add='+')
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.limit.trace_add('write', lambda *_: self.update_sliders())
        self.light.trace_add('write', lambda *_: self.update_sliders())
        self.update_sliders()
        self.log('Симулятор готов. Изображение и телеметрия синтетические.')
        self.refresh()
        self.draw_camera()
        self.after_id = self.after(50, self.tick)

    @property
    def recording(self):
        return self.recorder is not None

    def setup_style(self):
        s = ttk.Style(self)
        s.theme_use('clam')
        s.configure('TButton', font=('Segoe UI', -13), padding=(10, 7), background='#23384e', foreground=TEXT, borderwidth=0)
        s.map('TButton', background=[('disabled', '#172436'), ('active', '#34516b')], foreground=[('disabled', '#65778a')])
        s.configure('Accent.TButton', background='#147b73', foreground='white')
        s.map('Accent.TButton', background=[('active', '#199d91'), ('disabled', '#243d45')])
        s.configure('Danger.TButton', background='#a73549', foreground='white')
        s.map('Danger.TButton', background=[('active', '#cd465d')])
        s.configure('TScale', background=PANEL, troughcolor=BG)
        s.configure('TEntry', fieldbackground=BG, foreground=TEXT, insertcolor=TEXT, padding=7)
        s.configure('TNotebook', background=BG, borderwidth=0)
        s.configure('TNotebook.Tab', background=PANEL, foreground=MUTED, padding=(14, 7), font=('Segoe UI', -13))
        s.map('TNotebook.Tab', background=[('selected', '#20374b')], foreground=[('selected', CYAN)])
        s.configure('Vertical.TScrollbar', background=EDGE, troughcolor=PANEL, borderwidth=0, arrowsize=12)
        s.configure('Horizontal.TProgressbar', troughcolor=BG, background=CYAN, borderwidth=0, thickness=4)

    def label(self, parent, text='', size=10, color=TEXT, bold=False, **kwargs):
        return tk.Label(parent, text=text, bg=parent.cget('bg'), fg=color,
                        font=('Segoe UI', -round(size * 1.3), 'bold' if bold else 'normal'), **kwargs)

    def panel(self, parent, name, title):
        f = tk.Frame(parent, bg=PANEL, padx=13, pady=10, highlightbackground=EDGE, highlightthickness=1)
        self.label(f, title, 9, MUTED, bold=True).pack(anchor='w', pady=(0, 8))
        self.panels[name] = f
        return f

    def build(self):
        footer = tk.Frame(self, bg=BG, padx=18, pady=7)
        footer.pack(side='bottom', fill='x')
        self.notice_widget = self.label(footer, size=9, color=MUTED, anchor='w', textvariable=self.notice)
        self.notice_widget.pack(fill='x')
        self.notice_widget.bind('<Configure>', lambda e: self.notice_widget.configure(wraplength=max(200, e.width - 10)))
        safety = tk.Frame(self, bg=PANEL, padx=18, pady=9, highlightthickness=1, highlightbackground=EDGE)
        safety.pack(side='bottom', fill='x', padx=18)
        self.panels['safety'] = safety
        ttk.Button(safety, text='Стоп движения · Space', command=self.stop).pack(side='left')
        ttk.Button(safety, text='Аварийный стоп · Esc', style='Danger.TButton', command=self.emergency_stop).pack(side='left', padx=10)
        self.reset_button = ttk.Button(safety, text='Сброс аварии', command=self.reset_emergency)
        self.reset_button.pack(side='left')
        ttk.Button(safety, text='Новый сеанс', command=self.new_session).pack(side='right')
        header = tk.Frame(self, bg=BG, padx=20, pady=6)
        header.pack(fill='x')
        brand = tk.Frame(header, bg=BG)
        brand.pack(side='left')
        self.label(brand, 'Н Е Р Е Й', 23, bold=True).pack(anchor='w')
        self.label(brand, 'ПУЛЬТ ПОДВОДНОГО АППАРАТА / СИМУЛЯТОР', 8, MUTED).pack(anchor='w')
        self.connect_button = ttk.Button(header, text='Подключить', style='Accent.TButton', command=self.connect)
        self.connect_button.pack(side='right')
        self.panels['connection'] = header
        ttk.Button(header, text='Обучение', command=self.show_training).pack(side='right', padx=8)
        ttk.Button(header, text='Справка · F1', command=self.show_help).pack(side='right')
        self.status_widget = self.label(header, textvariable=self.status, color=CYAN, bold=True)
        self.status_widget.pack(side='right', padx=14)
        self.alarm_widget = tk.Label(self, textvariable=self.alarm, bg='#132c32', fg=CYAN, anchor='w', padx=14, pady=7, font=('Segoe UI', -13))
        self.alarm_widget.pack(fill='x', padx=18, pady=(0, 10))
        strip = tk.Frame(self, bg=BG)
        strip.pack(fill='x', padx=18)
        for index, (key, title, hint) in enumerate((('depth', 'ГЛУБИНА', 'Диапазон 0–1000 м'), ('heading', 'КУРС', '0° — север'), ('speed', 'СКОРОСТЬ', '− назад / + вперёд'), ('distance', 'ДО ОБЪЕКТА', 'Защитный рубеж 3 м'), ('battery', 'БАТАРЕЯ', 'Предупреждение < 20%'))):
            f = tk.Frame(strip, bg=PANEL, padx=12, pady=7, highlightthickness=1, highlightbackground=EDGE)
            f.grid(row=0, column=index, sticky='nsew', padx=(0, 8) if index < 4 else 0)
            strip.columnconfigure(index, weight=1, uniform='metrics')
            self.label(f, title, 8, MUTED, bold=True).pack(anchor='w')
            self.metrics[key] = tk.StringVar(value='—')
            widget = self.label(f, textvariable=self.metrics[key], size=21, bold=True)
            widget.pack(anchor='w')
            self.metric_widgets[key] = widget
            detail = self.label(f, hint, 8, MUTED)
            detail.pack(anchor='w')
            self.compact_details.append(detail)
        body = tk.Frame(self, bg=BG)
        body.pack(fill='both', expand=True, padx=18, pady=8)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, minsize=310)
        body.rowconfigure(0, weight=1)
        left = tk.Frame(body, bg=BG)
        left.grid(row=0, column=0, sticky='nsew', padx=(0, 12))
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        cam = self.panel(left, 'camera', 'ОБСЛЕДОВАНИЕ ГТС / ОСНОВНАЯ КАМЕРА')
        cam.grid(row=0, column=0, sticky='nsew', pady=(0, 10))
        self.camera = tk.Canvas(cam, bg='#06121d', height=180, highlightthickness=0, takefocus=True)
        self.camera.bind('<Configure>', lambda e: self.draw_camera())
        self.camera.bind('<Button-1>', lambda e: self.camera.focus_set())
        bar = tk.Frame(cam, bg=PANEL)
        bar.pack(side='bottom', fill='x', pady=(9, 0))
        self.camera.pack(fill='both', expand=True)
        self.snapshot_button = ttk.Button(bar, text='Снимок PNG', command=self.snapshot)
        self.snapshot_button.pack(side='left')
        self.record_button = ttk.Button(bar, text='● Запись AVI + CSV', command=self.toggle_record)
        self.record_button.pack(side='left', padx=8)
        self.label(bar, textvariable=self.record_status, size=8, color=MUTED).pack(side='right')
        self.tabs = ttk.Notebook(left, height=142)
        self.tabs.grid(row=1, column=0, sticky='ew')
        self.training_tab = tk.Frame(self.tabs, bg=PANEL, padx=14, pady=10)
        self.journal_tab = tk.Frame(self.tabs, bg=PANEL, padx=12, pady=8)
        self.tabs.add(self.training_tab, text='Обучение оператора')
        self.tabs.add(self.journal_tab, text='Журнал событий')
        self.build_training()
        log_bar = tk.Frame(self.journal_tab, bg=PANEL)
        log_bar.pack(side='bottom', fill='x', pady=(6, 0))
        self.label(log_bar, 'Последние 1000 событий', 8, MUTED).pack(side='left')
        ttk.Button(log_bar, text='Сохранить TXT', command=self.export_log).pack(side='right')
        log_area = tk.Frame(self.journal_tab, bg=PANEL)
        log_area.pack(fill='both', expand=True)
        self.journal = tk.Text(log_area, bg=BG, fg=MUTED, font=('Consolas', -12), relief='flat', height=4, wrap='word', state='disabled')
        scrollbar = ttk.Scrollbar(log_area, command=self.journal.yview)
        scrollbar.pack(side='right', fill='y')
        self.journal.configure(yscrollcommand=scrollbar.set)
        self.journal.pack(fill='both', expand=True)
        scroll_host = tk.Frame(body, bg=BG, width=310)
        scroll_host.grid(row=0, column=1, sticky='nsew')
        scroll_host.grid_propagate(False)
        scroll_host.rowconfigure(0, weight=1)
        scroll_host.columnconfigure(0, weight=1)
        self.side_canvas = tk.Canvas(scroll_host, bg=BG, highlightthickness=0, width=294)
        self.side_canvas.grid(row=0, column=0, sticky='nsew')
        side_scroll = ttk.Scrollbar(scroll_host, command=self.side_canvas.yview)
        side_scroll.grid(row=0, column=1, sticky='ns')
        self.side_canvas.configure(yscrollcommand=side_scroll.set)
        self.side = tk.Frame(self.side_canvas, bg=BG)
        window = self.side_canvas.create_window(0, 0, window=self.side, anchor='nw')
        self.side.bind('<Configure>', lambda e: self.side_canvas.configure(scrollregion=self.side_canvas.bbox('all')))
        self.side_canvas.bind('<Configure>', lambda e: self.side_canvas.itemconfigure(window, width=e.width))
        self.build_controls()
        self.bind_side_scroll(self.side)

    def resize_layout(self, event):
        if event.widget is not self:
            return
        compact = event.height < 760
        if compact == self.compact:
            return
        self.compact = compact
        for widget in self.compact_details:
            widget.pack_forget() if compact else widget.pack(anchor='w')

    def build_controls(self):
        controls = self.panel(self.side, 'controls', '01 / ДВИЖЕНИЕ')
        controls.pack(fill='x', pady=(0, 10))
        self.label(controls, 'Удерживайте кнопку или клавишу', 9, MUTED).pack(anchor='w')
        pad = tk.Frame(controls, bg=PANEL)
        pad.pack(fill='x', pady=8)
        for col in range(3):
            pad.columnconfigure(col, weight=1, uniform='pad')
        for text, key, row, col in (('W\nВперёд', 'w', 0, 1), ('A\nПоворот ↶', 'a', 1, 0), ('S\nНазад', 's', 1, 1), ('D\nПоворот ↷', 'd', 1, 2), ('Q\nВверх', 'q', 0, 0), ('E\nВниз', 'e', 0, 2)):
            b = tk.Button(pad, text=text, bg='#20354a', fg=TEXT, activebackground='#167e77', activeforeground='white', disabledforeground='#647589', relief='flat', bd=0, font=('Segoe UI', -13), pady=7, takefocus=False)
            b.grid(row=row, column=col, sticky='ew', padx=3, pady=3)
            b.bind('<ButtonPress-1>', lambda e, k=key: self.mouse_press(k))
            b.bind('<ButtonRelease-1>', lambda e, k=key: self.command_end(k, 'mouse'))
            b.bind('<Leave>', lambda e, k=key: self.command_end(k, 'mouse'))
            self.movement_buttons[key] = b
        self.label(controls, textvariable=self.limit_label, color=CYAN, size=9).pack(anchor='w')
        ttk.Scale(controls, from_=.1, to=1.5, variable=self.limit).pack(fill='x', pady=(2, 0))
        depth = self.panel(self.side, 'depth', '02 / ГЛУБИНА И ОСВЕЩЕНИЕ')
        depth.pack(fill='x', pady=(0, 10))
        row = tk.Frame(depth, bg=PANEL)
        row.pack(fill='x')
        self.depth_entry = ttk.Entry(row, textvariable=self.target, width=7, font=('Segoe UI', -16))
        self.depth_entry.pack(side='left')
        self.label(row, 'м', 10, MUTED).pack(side='left', padx=5)
        self.hold_button = ttk.Button(row, text='Удерживать', command=self.toggle_hold)
        self.hold_button.pack(side='right')
        self.depth_feedback = self.label(depth, 'Допустимая глубина: 0–1000 м', 9, MUTED, anchor='w')
        self.depth_feedback.pack(fill='x', pady=(4, 9))
        self.label(depth, textvariable=self.light_label, size=9, color=CYAN).pack(anchor='w')
        ttk.Scale(depth, from_=0, to=100, variable=self.light).pack(fill='x')
        nav = self.panel(self.side, 'navigation', '03 / ПОЛОЖЕНИЕ В ПЛАНЕ')
        nav.pack(fill='x')
        self.map = tk.Canvas(nav, height=145, bg=BG, highlightthickness=0)
        self.map.pack(fill='x')
        self.map.bind('<Configure>', lambda e: self.draw_map())
        self.label(nav, '● ГТС   △ НПА   ○ рубеж 3 м\nСхема симуляции · радиус зоны 100 м', 8, MUTED, justify='left').pack(anchor='w', pady=(6, 0))

    def build_training(self):
        self.training_title = self.label(self.training_tab, 'Освойте пульт за несколько минут', 12, bold=True)
        self.training_title.pack(anchor='w')
        self.training_text = self.label(self.training_tab, '8 практических шагов: от подключения до аварийной остановки. Можно начать заново в любой момент.', 10, MUTED, justify='left', anchor='w', wraplength=560)
        self.training_text.pack(fill='x', pady=(5, 6))
        self.training_text.bind('<Configure>', lambda e: self.training_text.configure(wraplength=max(200, e.width - 4)))
        self.progress = ttk.Progressbar(self.training_tab, maximum=len(LESSONS))
        self.progress.pack(fill='x', pady=(0, 7))
        row = tk.Frame(self.training_tab, bg=PANEL)
        row.pack(fill='x')
        self.training_result = self.label(row, 'Практика в симуляторе', 9, MUTED)
        self.training_result.pack(side='left')
        self.next_button = ttk.Button(row, text='Начать обучение', style='Accent.TButton', command=self.training_next)
        self.next_button.pack(side='right')
        self.exit_training = ttk.Button(row, text='Завершить', command=self.training_exit)

    def install_key_bindings(self, widget):
        tags = widget.bindtags()
        widget.bindtags((tags[0], 'PilotKeys') + tuple(t for t in tags[1:] if t != 'PilotKeys'))
        for child in widget.winfo_children():
            self.install_key_bindings(child)

    def bind_side_scroll(self, widget):
        widget.bind('<MouseWheel>', self.scroll_side)
        for child in widget.winfo_children():
            self.bind_side_scroll(child)

    def scroll_side(self, event):
        self.side_canvas.yview_scroll(-int(event.delta / 120), 'units')
        return 'break'

    def update_sliders(self):
        self.limit_label.set(f'Скорость до {self.limit.get():.2f} м/с')
        self.light_label.set(f'Прожектор · {self.light.get():.0f}%')

    def log(self, message):
        line = f'{datetime.now():%H:%M:%S}  {message}'
        self.log_lines.append(line)
        self.journal.configure(state='normal')
        self.journal.insert('end', line + '\n')
        if int(self.journal.index('end-1c').split('.')[0]) > 1001:
            self.journal.delete('1.0', '2.0')
        self.journal.see('end')
        self.journal.configure(state='disabled')

    def notify(self, text):
        self.notice.set(text)
        self.log(text)

    def mark(self, event):
        self.events[event] = self.events.get(event, 0) + 1
        if self.lesson is not None and event == LESSONS[self.lesson][2] and self.events[event] > self.lesson_baseline:
            self.lesson_done = True
            self.training_result.configure(text='✓ Задание выполнено', fg=CYAN)
            self.next_button.configure(state='normal')
            self.progress['value'] = self.lesson + 1

    def allowed(self):
        return self.vehicle.connected and not self.vehicle.emergency

    def inhibit(self):
        self.inputs.inhibit()
        self.vehicle.stop()

    def command_start(self, key, source='keyboard'):
        self.vehicle.commands = self.inputs.press(source, key, self.allowed())

    def command_end(self, key, source='keyboard'):
        commands = self.inputs.release(source, key)
        self.vehicle.commands = commands if self.allowed() else set()

    def mouse_press(self, key):
        self.camera.focus_set()
        self.command_start(key, 'mouse')
        return 'break'

    def mouse_release(self, event=None):
        for source, key in list(self.inputs.held):
            if source == 'mouse':
                self.command_end(key, source)

    @staticmethod
    def event_key(event):
        return {87: 'w', 65: 'a', 83: 's', 68: 'd', 81: 'q', 69: 'e'}.get(event.keycode, event.keysym.lower())

    def key_press(self, event):
        if event.keysym == 'F1':
            self.show_help()
            return 'break'
        if event.keysym in ('Escape', 'space'):
            token = ('shortcut', event.keysym)
            if token not in self.inputs.held:
                self.inputs.held.add(token)
                self.emergency_stop() if event.keysym == 'Escape' else self.stop()
            return 'break'
        key = self.event_key(event)
        if key in {'w', 'a', 's', 'd', 'q', 'e'}:
            focus = self.focus_get()
            if focus is not None and focus.winfo_toplevel() is not self:
                return
            editing = isinstance(self.focus_get(), (ttk.Entry, tk.Entry, tk.Text))
            modified = bool(event.state & (0x4 | 0x8 | 0x20000))
            if editing or modified:
                self.inputs.press('keyboard', key, False)
                return
            self.command_start(key)
            return 'break'

    def key_release(self, event):
        self.inputs.release('shortcut', event.keysym)
        self.command_end(self.event_key(event))

    def focus_out(self, event=None):
        if self.focus_job is None and not self.closed:
            self.focus_job = self.after_idle(self.check_focus)

    def check_focus(self):
        self.focus_job = None
        focus = self.focus_get()
        if focus is None or focus.winfo_toplevel() is not self or isinstance(focus, (ttk.Entry, tk.Entry, tk.Text)):
            active = bool(self.vehicle.commands or self.vehicle.hold)
            self.inhibit()
            self.mouse_release()
            if active:
                self.notify('Окно неактивно: движение и удержание остановлены.')

    def connect(self):
        self.inhibit()
        self.vehicle.connected = not self.vehicle.connected
        if self.vehicle.connected:
            self.mark('connected')
            self.notify('Симулятор подключён. Управляйте кнопками или W/A/S/D, Q/E.')
        else:
            self.finish_record()
            self.notify('Связь отключена. Все команды остановлены.')
        self.camera.focus_set()
        self.refresh()
        self.draw_camera()

    def stop(self):
        self.inhibit()
        self.mark('stopped')
        self.notify('Стоп. Отпустите удерживаемые клавиши перед новой командой.')
        self.refresh()

    def emergency_stop(self):
        if not self.vehicle.emergency:
            self.inhibit()
            self.vehicle.trip('Аварийный стоп оператора')
            self.mark('emergency')
            self.notify('Аварийный стоп включён. Для продолжения выполните сброс.')
        self.refresh()

    def reset_emergency(self):
        if not self.vehicle.emergency:
            return
        if self.vehicle.battery <= 0:
            self.notify('Батарея разряжена. Нажмите «Новый сеанс» для перезапуска симуляции.')
            return
        self.inhibit()
        self.vehicle.emergency = False
        self.vehicle.emergency_reason = ''
        self.mark('reset')
        self.notify('Авария сброшена. Аппарат ожидает новую команду.')
        self.camera.focus_set()
        self.refresh()

    def toggle_hold(self):
        v = self.vehicle
        if not self.allowed():
            return
        if v.hold:
            v.hold = False
            v.vertical_speed = 0
            self.notify('Удержание глубины отключено.')
        else:
            try:
                value = float(self.target.get().strip().replace(',', '.'))
                if not math.isfinite(value) or not 0 <= value <= 1000:
                    raise ValueError
            except ValueError:
                self.depth_feedback.configure(text='Введите число от 0 до 1000 м', fg=RED)
                self.depth_entry.focus_set()
                self.depth_entry.selection_range(0, 'end')
                return
            self.inhibit()
            v.target, v.hold = value, True
            self.notify(f'Удержание глубины: цель {value:.1f} м.')
            self.camera.focus_set()
        self.refresh()

    def new_session(self):
        self.finish_record()
        self.inhibit()
        self.vehicle = Vehicle()
        self.target.set('122')
        self.limit.set(.5)
        self.light.set(65)
        self.alert_previous = ''
        self.frame_rgb = None
        self.depth_feedback.configure(text='?????????? ???????: 0?1000 ?', fg=MUTED)
        self.training_exit(silent=True)
        self.notify('Новый сеанс готов. Сохранённые файлы остаются в captures.')
        self.refresh()
        self.draw_camera()

    def snapshot(self):
        if not self.vehicle.connected:
            return
        try:
            OUTPUT.mkdir(parents=True, exist_ok=True)
            name = datetime.now().strftime('frame_%Y%m%d_%H%M%S_%f')
            path = OUTPUT / (name + '.png')
            image = tk.PhotoImage(data=ppm(render(self.vehicle, self.light.get())), format='PPM', master=self)
            image.write(str(path), format='png')
            metadata = {key: getattr(self.vehicle, key) for key in ('depth', 'heading', 'distance', 'battery', 'x', 'y')}
            metadata.update(timestamp=datetime.now().astimezone().isoformat(), synthetic=True)
            path.with_suffix('.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
            self.mark('photo')
            self.notify(f'Сохранены PNG и показания JSON: {name}')
        except (OSError, tk.TclError) as error:
            self.notify(f'Не удалось полностью сохранить снимок: {error}')

    def toggle_record(self):
        if self.recording:
            self.finish_record()
            return
        if not self.vehicle.connected:
            return
        try:
            self.recorder = SessionRecorder(OUTPUT)
            self.record_started = time.monotonic()
            self.recorder.write(self.vehicle, render(self.vehicle, self.light.get()), 0)
            self.notify('Идёт запись AVI + CSV, 480×270, 4 кадра/с. Около 90 МБ/мин.')
        except (OSError, ValueError) as error:
            self.finish_record(mark=False)
            self.notify(f'Ошибка начала записи: {error}')
        self.refresh()

    def finish_record(self, mark=True):
        recorder, self.recorder = self.recorder, None
        if recorder is None:
            return
        try:
            recorder.close()
            if mark:
                self.mark('recorded')
            self.notify(f'Запись сохранена: {recorder.video_path.name} и CSV.')
        except OSError as error:
            self.notify(f'Ошибка завершения записи; файлы могут быть неполными: {error}')
        self.refresh()

    def export_log(self):
        try:
            OUTPUT.mkdir(parents=True, exist_ok=True)
            path = OUTPUT / datetime.now().strftime('journal_%Y%m%d_%H%M%S_%f.txt')
            path.write_text('\n'.join(self.log_lines) + '\n', encoding='utf-8')
            self.notify(f'Журнал сохранён: {path.name}')
        except OSError as error:
            self.notify(f'Ошибка сохранения журнала: {error}')

    def show_training(self):
        self.tabs.select(self.training_tab)
        if self.lesson is not None:
            self.highlight(LESSONS[self.lesson][3])

    def training_next(self):
        if self.lesson is None:
            self.new_session()
            self.lesson = 0
            self.exit_training.pack(side='right', padx=6)
        elif not self.lesson_done:
            return
        elif self.lesson == len(LESSONS) - 1:
            self.inhibit()
            self.training_exit(silent=True)
            self.training_title.configure(text='Обучение завершено')
            self.training_text.configure(text='Вы освоили основные действия. Продолжайте обследование или начните обучение заново. Справка доступна по F1.')
            self.training_result.configure(text='✓ 8 из 8 заданий выполнено', fg=CYAN)
            self.progress['value'] = len(LESSONS)
            self.notify('Обучение завершено: все 8 заданий выполнены.')
            return
        else:
            self.lesson += 1
        title, instruction, event, panel = LESSONS[self.lesson]
        self.lesson_baseline = self.events.get(event, 0)
        self.lesson_done = False
        if event == 'depth':
            self.target.set('122')
        self.training_title.configure(text=f'{self.lesson + 1:02d} / {len(LESSONS):02d}   {title}')
        self.training_text.configure(text=instruction)
        self.training_result.configure(text='Выполните действие в пульте', fg=MUTED)
        self.next_button.configure(text='Завершить обучение' if self.lesson == len(LESSONS) - 1 else 'Далее →', state='disabled')
        self.progress['value'] = self.lesson
        self.tabs.select(self.training_tab)
        self.highlight(panel)

    def training_exit(self, silent=False):
        self.lesson = None
        self.lesson_done = False
        self.highlight(None)
        self.exit_training.pack_forget()
        self.next_button.configure(text='Начать заново' if silent else 'Начать обучение', state='normal')
        self.training_title.configure(text='Обучение оператора')
        self.training_text.configure(text='8 практических шагов. Начало обучения создаёт новый сеанс симуляции; записанные файлы сохраняются.')
        self.training_result.configure(text='Можно пройти в любое время', fg=MUTED)
        self.progress['value'] = 0
        if not silent:
            self.inhibit()
            self.notify('Обучение завершено досрочно. Можно вернуться в любой момент.')

    def highlight(self, name):
        if self.highlighted:
            self.highlighted.configure(highlightbackground=EDGE, highlightthickness=1)
        self.highlighted = self.panels.get(name)
        if self.highlighted:
            self.highlighted.configure(highlightbackground=CYAN, highlightthickness=2)
            if name in ('controls', 'depth'):
                self.update_idletasks()
                total = max(1, self.side.winfo_height())
                self.side_canvas.yview_moveto(self.highlighted.winfo_y() / total)

    def show_help(self):
        self.inhibit()
        if hasattr(self, 'help_window') and self.help_window.winfo_exists():
            self.help_window.lift()
            return
        self.help_window = top = tk.Toplevel(self)
        top.title('Справка · Нерей')
        top.geometry('620x540')
        top.configure(bg=PANEL)
        top.transient(self)
        text = tk.Text(top, bg=PANEL, fg=TEXT, padx=22, pady=20, wrap='word', relief='flat', font=('Segoe UI', -14))
        scrollbar = ttk.Scrollbar(top, command=text.yview)
        scrollbar.pack(side='right', fill='y')
        text.configure(yscrollcommand=scrollbar.set)
        ttk.Button(top, text='Понятно', command=top.destroy).pack(side='bottom', pady=12)
        text.pack(fill='both', expand=True)
        text.insert('1.0', 'УПРАВЛЕНИЕ ПУЛЬТОМ\n\nW / S — вперёд / назад по текущему курсу.\nA / D — поворот влево / вправо.\nQ / E — всплытие / погружение.\nSpace — остановка движения и удержания глубины.\nEsc — аварийный стоп, в том числе при вводе глубины.\nF1 — эта справка.\n\nПосле стопа отпустите клавиши перед новой командой. При потере фокуса движение и удержание останавливаются. Русская раскладка поддерживается в Windows.\n\nГЛУБИНА И ЗАЩИТА\nВведите 0–1000 м и нажмите «Удерживать». Q/E отменяет удержание. На расстоянии 3 м до центра условного объекта сближение блокируется. Поворот и отход доступны. Красный аварийный статус остаётся до сброса.\n\nЗАПИСЬ\nPNG + JSON — кадр сцены и показания. AVI + CSV — синтетическое видео 480×270, 4 кадра/с и телеметрия. AVI несжатое, около 90 МБ/мин, лимит 1 ГБ. При задержках интерфейса возможны пропуски кадров; точное время есть в CSV. Файлы находятся в captures рядом с main.py.\n\nМОДЕЛЬ\nЭто учебный симулятор. Движение, заряд, защитные зоны и камера условные. «Новый сеанс» восстанавливает начальное состояние. Вкладка «Обучение» содержит 8 практических заданий.')
        text.configure(state='disabled')
        self.install_key_bindings(top)

    def refresh(self):
        v = self.vehicle
        self.connect_button.configure(text='Отключить' if v.connected else 'Подключить')
        self.status.set('● АВАРИЯ' if v.emergency else '● НА СВЯЗИ' if v.connected else '○ НЕТ СВЯЗИ')
        self.status_widget.configure(fg=RED if v.emergency else CYAN if v.connected else MUTED)
        for key, value, suffix in (('depth', v.depth, 'м'), ('heading', v.heading, '°'), ('speed', v.speed, 'м/с'), ('distance', v.distance, 'м'), ('battery', v.battery, '%')):
            self.metrics[key].set(f'{value:.1f} {suffix}' if v.connected else '—')
        self.metric_widgets['distance'].configure(fg=AMBER if v.distance <= 5 and v.connected else TEXT)
        self.metric_widgets['battery'].configure(fg=AMBER if v.battery < 20 and v.connected else TEXT)
        if v.emergency:
            alarm, color, background = f'АВАРИЯ / {v.emergency_reason}. Движение заблокировано.', RED, '#381d2a'
        elif not v.connected:
            alarm, color, background = 'ОЖИДАНИЕ / Подключите симулятор. Можно начать со встроенного обучения.', MUTED, '#172433'
        elif v.distance <= 3.05:
            alarm, color, background = 'ЗАЩИТНЫЙ РУБЕЖ / 3 м до объекта. Развернитесь или выполните отход.', AMBER, '#342b1d'
        elif v.battery < 20:
            alarm, color, background = 'НИЗКИЙ ЗАРЯД / Менее 20%. Завершите обследование.', AMBER, '#342b1d'
        elif v.hold:
            alarm, color, background = f'СТАБИЛИЗАЦИЯ / Цель {v.target:.1f} м · вертикальная скорость {v.vertical_speed:+.2f} м/с', CYAN, '#132c32'
        else:
            alarm, color, background = 'РУЧНОЙ РЕЖИМ / W A S D — движение и курс · Q E — глубина · Space — стоп', CYAN, '#132c32'
        self.alarm.set(alarm)
        self.alarm_widget.configure(fg=color, bg=background)
        enabled = self.allowed()
        for key, button in self.movement_buttons.items():
            button.configure(state='normal' if enabled else 'disabled', bg='#167b73' if key in v.commands else '#20354a')
        self.hold_button.configure(state='normal' if enabled else 'disabled', text='Отключить' if v.hold else 'Удерживать')
        if v.hold:
            self.depth_feedback.configure(text=f'Цель {v.target:.1f} м · ошибка {v.target - v.depth:+.1f} м', fg=CYAN)
        elif self.depth_feedback.cget('fg') != RED:
            self.depth_feedback.configure(text='Допустимая глубина: 0–1000 м', fg=MUTED)
        self.snapshot_button.configure(state='normal' if v.connected else 'disabled')
        self.record_button.configure(state='normal' if v.connected else 'disabled', text='■ Завершить запись' if self.recording else '● Запись AVI + CSV')
        self.reset_button.configure(state='normal' if v.emergency else 'disabled')
        if self.recording:
            elapsed = int(time.monotonic() - self.record_started)
            self.record_status.set(f'REC {elapsed // 60:02d}:{elapsed % 60:02d}')
        else:
            self.record_status.set('КАМЕРА 01 / SIM')
        alert = 'battery' if v.connected and v.battery < 20 else 'range' if v.connected and v.distance <= 3.05 else ''
        if alert and alert != self.alert_previous:
            self.log('Внимание: низкий заряд батареи.' if alert == 'battery' else 'Достигнут защитный рубеж 3 м.')
        self.alert_previous = alert

    def draw_camera(self):
        c = self.camera
        c.delete('all')
        w, h = max(1, c.winfo_width()), max(1, c.winfo_height())
        if not self.vehicle.connected:
            for xx in range(0, w, 40):
                c.create_line(xx, 0, xx, h, fill='#102435')
            for yy in range(0, h, 40):
                c.create_line(0, yy, w, yy, fill='#102435')
            c.create_text(w / 2, h / 2 - 12, text='КАМЕРА ОЖИДАЕТ ПОДКЛЮЧЕНИЯ', fill=TEXT, font=('Segoe UI', -16, 'bold'))
            c.create_text(w / 2, h / 2 + 16, text='Синтетическая подводная сцена · режим SIM', fill=MUTED, font=('Segoe UI', -13))
            return
        if self.frame_rgb is None:
            self.frame_rgb = render(self.vehicle, self.light.get())
        pixels = render(self.vehicle, self.light.get(), time.monotonic() - self.clock_started, w, h)
        self.frame_image = tk.PhotoImage(data=ppm(pixels, w, h), format='PPM', master=self)
        c.create_image(w / 2, h / 2, image=self.frame_image)
        cx, cy = w / 2, h / 2
        for sign in (-1, 1):
            c.create_line(cx + sign * 12, cy, cx + sign * 30, cy, fill=CYAN)
            c.create_line(cx, cy + sign * 12, cx, cy + sign * 30, fill=CYAN)
        c.create_oval(cx - 3, cy - 3, cx + 3, cy + 3, outline=CYAN)
        c.create_text(13, 12, text='CAM 01 · SIM', anchor='nw', fill=CYAN, font=('Consolas', -13, 'bold'))
        c.create_text(w - 13, 12, text=f'КУРС {self.vehicle.heading:05.1f}°', anchor='ne', fill=TEXT, font=('Consolas', -13))
        c.create_text(13, h - 12, text=f'ГЛУБИНА {self.vehicle.depth:06.1f} м', anchor='sw', fill=TEXT, font=('Consolas', -13))
        c.create_text(w - 13, h - 12, text=f'ДИСТ. {self.vehicle.distance:05.1f} м', anchor='se', fill=TEXT, font=('Consolas', -13))
        if self.vehicle.emergency:
            c.create_rectangle(cx - 120, 35, cx + 120, 65, fill='#381d2a', outline=RED)
            c.create_text(cx, 50, text='АВАРИЙНЫЙ СТОП', fill=RED, font=('Segoe UI', -14, 'bold'))

    def draw_map(self):
        c = self.map
        c.delete('all')
        w, h = max(1, c.winfo_width()), max(1, c.winfo_height())
        cx, cy = w / 2, h / 2
        scale = min(w, h) / (max(24, self.vehicle.distance * 1.25) * 2)
        for distance in (3, 10, 20):
            radius = distance * scale
            c.create_oval(cx - radius, cy - radius, cx + radius, cy + radius, outline=AMBER if distance == 3 else EDGE, dash=() if distance == 3 else (2, 4))
        c.create_line(cx, 5, cx, h - 5, fill=EDGE)
        c.create_line(5, cy, w - 5, cy, fill=EDGE)
        c.create_text(w - 14, 12, text='N ↑', fill=MUTED, font=('Segoe UI', -12))
        c.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, fill=AMBER, outline='')
        if self.vehicle.connected:
            x, y = cx + self.vehicle.x * scale, cy - self.vehicle.y * scale
            angle = math.radians(self.vehicle.heading)
            points = []
            for offset, length in ((0, 9), (2.5, 7), (-2.5, 7)):
                points.extend((x + math.sin(angle + offset) * length, y - math.cos(angle + offset) * length))
            c.create_polygon(points, fill=CYAN, outline=TEXT)

    def tick(self):
        if self.closed:
            return
        self.after_id = None
        now = time.monotonic()
        dt = min(.25, now - self.last_tick)
        self.last_tick = now
        v = self.vehicle
        before = (v.x, v.y, v.depth, v.heading)
        was_emergency = v.emergency
        v.step(dt, self.limit.get())
        if before != (v.x, v.y, v.depth, v.heading):
            self.mark('moved')
        if v.emergency and not was_emergency:
            self.inhibit()
            self.log(v.emergency_reason)
        if self.lesson is not None and LESSONS[self.lesson][2] == 'depth' and v.hold and abs(v.depth - 122) < .05 and abs(v.target - 122) < .01:
            self.mark('depth')
        if now - self.last_frame >= .25:
            self.last_frame = now
            if v.connected:
                self.frame_rgb = render(v, self.light.get(), now - self.clock_started)
                if self.recording:
                    try:
                        self.recorder.write(v, self.frame_rgb, now - self.record_started)
                    except (OSError, ValueError) as error:
                        self.finish_record(mark=False)
                        self.notify(f'Запись остановлена из-за ошибки: {error}')
            self.draw_camera()
            self.draw_map()
        self.refresh()
        self.after_id = self.after(50, self.tick)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.inhibit()
        for job in (self.after_id, self.focus_job):
            if job is not None:
                self.after_cancel(job)
        self.finish_record()
        self.destroy()


def main():
    Console().mainloop()


if __name__ == '__main__':
    main()

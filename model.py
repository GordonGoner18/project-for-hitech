"""Состояние симулятора и защита от повторных команд после остановки."""
from dataclasses import dataclass, field
import math


@dataclass
class Vehicle:
    connected: bool = False
    emergency: bool = False
    emergency_reason: str = ""
    depth: float = 120.0
    heading: float = 0.0
    x: float = 0.0
    y: float = -18.0
    battery: float = 96.0
    speed: float = 0.0
    vertical_speed: float = 0.0
    hold: bool = False
    target: float = 120.0
    commands: set = field(default_factory=set)

    @property
    def distance(self):
        return math.hypot(self.x, self.y)

    def stop(self):
        self.commands.clear()
        self.speed = self.vertical_speed = 0.0
        self.hold = False

    def trip(self, reason):
        self.emergency = True
        self.emergency_reason = reason
        self.stop()

    def step(self, dt, limit):
        if not math.isfinite(dt) or dt <= 0:
            return
        dt = min(dt, 0.25)
        limit = min(1.5, max(0.1, limit))
        if not self.connected or self.emergency:
            self.stop()
            return
        if self.battery <= 0:
            self.trip("Батарея разряжена")
            return
        c = self.commands
        self.heading = (self.heading + (int('d' in c) - int('a' in c)) * 25 * dt) % 360
        forward = int('w' in c) - int('s' in c)
        requested = forward * limit
        angle = math.radians(self.heading)
        nx = self.x + math.sin(angle) * requested * dt
        ny = self.y + math.cos(angle) * requested * dt
        radius = math.hypot(nx, ny)
        self.speed = requested
        if radius < 3:
            nx, ny = nx * 3 / max(radius, 1e-9), ny * 3 / max(radius, 1e-9)
            self.speed = 0.0
        elif radius > 100:
            nx, ny = nx * 100 / radius, ny * 100 / radius
            self.speed = 0.0
        self.x, self.y = nx, ny
        vertical = int('e' in c) - int('q' in c)
        before = self.depth
        if vertical:
            self.hold = False
            self.depth += vertical * limit * dt
        elif self.hold:
            self.depth += max(-limit * dt, min(limit * dt, self.target - self.depth))
        self.depth = max(0.0, min(1000.0, self.depth))
        self.vertical_speed = (self.depth - before) / dt
        self.battery = max(0.0, self.battery - dt * (0.002 + abs(self.speed) * .003 + abs(self.vertical_speed) * .003))
        if self.battery <= 0:
            self.trip("Батарея разряжена")


class InputGate:
    """Источники независимы; после стопа удерживаемые клавиши надо отпустить."""
    def __init__(self):
        self.held = set()
        self.blocked = set()

    def press(self, source, key, enabled):
        token = (source, key)
        if token not in self.held and not enabled:
            self.blocked.add(token)
        self.held.add(token)
        return self.commands if enabled else set()

    def release(self, source, key):
        token = (source, key)
        self.held.discard(token)
        self.blocked.discard(token)
        return self.commands

    def inhibit(self):
        self.blocked.update(self.held)

    @property
    def commands(self):
        return {key for source, key in self.held - self.blocked if source in ('keyboard', 'mouse')}

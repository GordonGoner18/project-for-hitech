"""Синтетическое изображение камеры. Только стандартная библиотека."""
import math

WIDTH, HEIGHT = 480, 270


class Raster:
    def __init__(self, width, height, light):
        self.w, self.h = width, height
        self.data = bytearray()
        for y in range(height):
            f = 1 - y / height
            color = bytes((int(3 + 5 * light + 3 * f), int(12 + 21 * light + 16 * f), int(22 + 28 * light + 23 * f)))
            self.data.extend(color * width)

    def span(self, x0, x1, y, color):
        x0, x1, y = max(0, int(x0)), min(self.w, int(x1)), int(y)
        if 0 <= y < self.h and x1 > x0:
            start = (y * self.w + x0) * 3
            self.data[start:start + (x1 - x0) * 3] = bytes(color) * (x1 - x0)

    def line(self, x0, y0, x1, y1, color):
        steps = max(1, int(max(abs(x1 - x0), abs(y1 - y0))))
        for i in range(steps + 1):
            t = i / steps
            self.span(round(x0 + (x1 - x0) * t), round(x0 + (x1 - x0) * t) + 1, round(y0 + (y1 - y0) * t), color)

    def ellipse(self, cx, cy, rx, ry, color):
        for y in range(max(0, int(cy - ry)), min(self.h, int(cy + ry + 1))):
            half = rx * math.sqrt(max(0, 1 - ((y - cy) / max(1, ry)) ** 2))
            self.span(cx - half, cx + half, y, color)


def render(vehicle, light=65, phase=0, width=WIDTH, height=HEIGHT):
    light = min(100, max(0, light)) / 100
    r = Raster(width, height, light)
    horizon = int(height * .55)
    grid = (12, int(30 + 12 * light), int(43 + 12 * light))
    for i in range(1, 7):
        yy = horizon + (i / 6) ** 2 * (height - horizon)
        r.line(0, yy, width, yy, grid)
    shift = math.sin(math.radians(vehicle.heading)) * width * .2
    for i in range(-4, 6):
        r.line(width / 2 + shift, horizon, i * width / 4 + shift, height, grid)
    bearing = math.degrees(math.atan2(-vehicle.x, -vehicle.y))
    relative = (bearing - vehicle.heading + 180) % 360 - 180
    if abs(relative) < 90:
        cx = width / 2 + relative / 70 * width
        cy = height * .56 + max(-height * .25, min(height * .25, (120 - vehicle.depth) * 2))
        scale = min(2.3, 12 / max(3, vehicle.distance))
        rx, ry = width * .19 * scale, height * .11 * scale
        r.ellipse(cx, cy + ry * 1.4, rx * 1.15, ry * .4, (5, 18, 27))
        # Эллипсоид условного ГТС, кольца и опоры.
        for y in range(int(cy - ry), int(cy + ry + 1)):
            f = (y - cy) / max(1, ry)
            half = rx * math.sqrt(max(0, 1 - f * f))
            shade = int((45 + 65 * math.sqrt(max(0, 1 - f * f)) - 15 * f) * (.25 + .75 * light))
            r.span(cx - half, cx + half, y, (shade, min(255, shade + 19), min(255, shade + 24)))
        for offset in (-.52, .52):
            x = cx + rx * offset
            r.line(x, cy - ry * .83, x, cy + ry * .83, (31, 62, 72))
            r.line(x, cy + ry * .7, x - rx * .08, cy + ry * 1.45, (38, 65, 73))
        r.ellipse(cx + rx * .55, cy - ry * .15, max(2, rx * .07), max(2, ry * .2), (44, 180, 161))
    for i in range(36):
        px = (i * 137 + int(phase * (2 + i % 4))) % width
        py = (i * 59 + int(phase * 3)) % height
        r.span(px, px + 1 + i % 2, py, (25, 63, 76))
    return bytes(r.data)


def ppm(rgb, width=WIDTH, height=HEIGHT):
    return f'P6\n{width} {height}\n255\n'.encode('ascii') + rgb

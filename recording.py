"""CSV + несжатое AVI: запись без сторонних библиотек и кодеков."""
import csv
import struct
from datetime import datetime
from pathlib import Path


def chunk(tag, data):
    return tag + struct.pack('<I', len(data)) + data + (b'\0' if len(data) % 2 else b'')


class AviWriter:
    def __init__(self, path, width=480, height=270, fps=4):
        self.width, self.height, self.fps = width, height, fps
        self.stride = (width * 3 + 3) & ~3
        self.frame_size = self.stride * height
        self.index = []
        self.file = Path(path).open('w+b')
        try:
            self.file.write(self.header(0, 0))
            self.movi_start = self.file.tell()
            self.file.write(b'LIST\0\0\0\0movi')
        except BaseException:
            self.file.close()
            raise

    def header(self, frames, riff_size):
        avih = struct.pack('<14I', int(1_000_000 / self.fps), self.frame_size * self.fps, 0, 0x10,
                           frames, 0, 1, self.frame_size, self.width, self.height, 0, 0, 0, 0)
        strh = struct.pack('<4s4sIHHIIIIIIIIhhhh', b'vids', b'DIB ', 0, 0, 0, 0, 1, self.fps,
                           0, frames, self.frame_size, 0xffffffff, 0, 0, 0, self.width, self.height)
        strf = struct.pack('<IiiHHIIiiII', 40, self.width, self.height, 1, 24, 0, self.frame_size, 0, 0, 0, 0)
        hdrl = chunk(b'LIST', b'hdrl' + chunk(b'avih', avih) + chunk(b'LIST', b'strl' + chunk(b'strh', strh) + chunk(b'strf', strf)))
        return b'RIFF' + struct.pack('<I', riff_size) + b'AVI ' + hdrl

    def write(self, rgb):
        if len(rgb) != self.width * self.height * 3:
            raise ValueError('Неверный размер видеокадра')
        if self.file.tell() > 1_000_000_000:
            raise OSError('Достигнут лимит AVI 1 ГБ. Начните новый сеанс.')
        bgr = bytearray(len(rgb))
        bgr[0::3], bgr[1::3], bgr[2::3] = rgb[2::3], rgb[1::3], rgb[0::3]
        row_size = self.width * 3
        padding = b'\0' * (self.stride - row_size)
        dib = b''.join(bgr[y * row_size:(y + 1) * row_size] + padding for y in range(self.height - 1, -1, -1))
        offset = self.file.tell() - self.movi_start - 8
        self.file.write(chunk(b'00db', dib))
        self.index.append((offset, len(dib)))

    def close(self):
        if self.file.closed:
            return
        try:
            end_movi = self.file.tell()
            self.file.write(chunk(b'idx1', b''.join(struct.pack('<4sIII', b'00db', 0x10, offset, size) for offset, size in self.index)))
            end = self.file.tell()
            self.file.seek(self.movi_start + 4)
            self.file.write(struct.pack('<I', end_movi - self.movi_start - 8))
            self.file.seek(0)
            self.file.write(self.header(len(self.index), end - 8))
            self.file.flush()
        finally:
            self.file.close()


class SessionRecorder:
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        name = datetime.now().strftime('session_%Y%m%d_%H%M%S_%f')
        self.csv_path = directory / (name + '.csv')
        self.video_path = directory / (name + '.avi')
        self.csv_file = self.csv_path.open('w', encoding='utf-8-sig', newline='')
        self.video = None
        try:
            self.writer = csv.writer(self.csv_file)
            self.writer.writerow(['timestamp', 'elapsed_s', 'depth_m', 'heading_deg', 'speed_m_s', 'vertical_m_s', 'distance_m', 'battery_pct', 'emergency'])
            self.csv_file.flush()
            self.video = AviWriter(self.video_path)
        except BaseException:
            self.csv_file.close()
            raise

    def write(self, vehicle, rgb, elapsed):
        self.video.write(rgb)
        self.writer.writerow([datetime.now().astimezone().isoformat(timespec='milliseconds'), round(elapsed, 3),
                              round(vehicle.depth, 2), round(vehicle.heading, 2), round(vehicle.speed, 2),
                              round(vehicle.vertical_speed, 2), round(vehicle.distance, 2), round(vehicle.battery, 2), vehicle.emergency])
        self.csv_file.flush()

    def close(self):
        errors = []
        for resource in (self.video, self.csv_file):
            if resource:
                try:
                    resource.close()
                except OSError as error:
                    errors.append(str(error))
        if errors:
            raise OSError('; '.join(errors))

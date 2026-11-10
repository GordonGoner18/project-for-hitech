"""Проверки модели, файлов записи и операторских сценариев."""
import csv
import json
import math
from pathlib import Path
import struct
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from model import InputGate, Vehicle
from recording import AviWriter, SessionRecorder
from scene import render
import main


class ModelTests(unittest.TestCase):
    def test_disconnect_and_emergency_cancel_all_motion(self):
        for connected, emergency in ((False, False), (True, True)):
            v = Vehicle(connected=connected, emergency=emergency, hold=True, commands={'w', 'e'})
            v.step(.2, 1)
            self.assertEqual((v.depth, v.distance), (120, 18))
            self.assertFalse(v.hold or v.commands)

    def test_heading_changes_direction(self):
        v = Vehicle(connected=True, heading=90, commands={'w'})
        v.step(.2, 1)
        self.assertAlmostEqual(v.x, .2)
        self.assertAlmostEqual(v.y, -18)

    def test_protected_radius_and_retreat(self):
        v = Vehicle(connected=True, y=-3.01, commands={'w'})
        v.step(.2, 1.5)
        self.assertAlmostEqual(v.distance, 3)
        self.assertEqual(v.speed, 0)
        v.commands = {'s'}
        v.step(.2, 1)
        self.assertGreater(v.distance, 3)

    def test_depth_bounds_and_manual_override(self):
        v = Vehicle(connected=True, depth=999.99, commands={'e'}, hold=True, target=100)
        v.step(.2, 1)
        self.assertEqual(v.depth, 1000)
        self.assertFalse(v.hold)
        v.depth, v.commands = .01, {'q'}
        v.step(.2, 1)
        self.assertEqual(v.depth, 0)

    def test_hold_reaches_target_without_overshoot(self):
        v = Vehicle(connected=True, hold=True, target=120.15)
        for _ in range(10):
            v.step(.2, 1)
        self.assertAlmostEqual(v.depth, 120.15)
        self.assertEqual(v.vertical_speed, 0)

    def test_empty_battery_latches_emergency(self):
        v = Vehicle(connected=True, battery=0, hold=True, commands={'w'})
        v.step(.1, 1)
        self.assertTrue(v.emergency)
        self.assertFalse(v.hold or v.commands)
        self.assertEqual(v.distance, 18)

    def test_stop_requires_release_even_after_repeat(self):
        gate = InputGate()
        self.assertEqual(gate.press('keyboard', 'w', True), {'w'})
        gate.inhibit()
        for _ in range(10):
            self.assertEqual(gate.press('keyboard', 'w', True), set())
        gate.release('keyboard', 'w')
        self.assertEqual(gate.press('keyboard', 'w', True), {'w'})

    def test_keyboard_and_mouse_do_not_cancel_each_other(self):
        gate = InputGate()
        gate.press('keyboard', 'w', True)
        gate.press('mouse', 'w', True)
        self.assertEqual(gate.release('mouse', 'w'), {'w'})
        self.assertEqual(gate.release('keyboard', 'w'), set())

    def test_preheld_disconnected_key_is_blocked(self):
        gate = InputGate()
        gate.press('keyboard', 'w', False)
        self.assertEqual(gate.press('keyboard', 'w', True), set())


class FileTests(unittest.TestCase):
    def test_avi_chunks_index_and_pixel_order(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.avi'
            writer = AviWriter(path, width=2, height=2)
            rgb = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255])
            writer.write(rgb)
            writer.write(rgb)
            writer.close()
            writer.close()
            data = path.read_bytes()
            self.assertEqual(data[:4], b'RIFF')
            self.assertEqual(struct.unpack_from('<I', data, 4)[0], len(data) - 8)
            avih = data.index(b'avih')
            self.assertEqual(struct.unpack_from('<I', data, avih + 8 + 16)[0], 2)
            movi = data.index(b'movi')
            idx = data.index(b'idx1')
            self.assertEqual(struct.unpack_from('<I', data, idx + 4)[0], 32)
            for i in range(2):
                tag, flags, offset, size = struct.unpack_from('<4sIII', data, idx + 8 + 16 * i)
                self.assertEqual(tag, b'00db')
                self.assertEqual(data[movi + offset:movi + offset + 4], tag)
                self.assertEqual(size, 16)
            frame = movi + 4 + 8
            self.assertEqual(data[frame:frame + 8], bytes([255, 0, 0, 255, 255, 255, 0, 0]))

    def test_session_csv_and_video_have_matching_frames(self):
        with tempfile.TemporaryDirectory() as folder:
            recorder = SessionRecorder(folder)
            v = Vehicle()
            for i in range(3):
                recorder.write(v, render(v), i / 4)
            recorder.close()
            with recorder.csv_path.open(encoding='utf-8-sig', newline='') as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[-1]['elapsed_s'], '0.5')
            self.assertGreater(recorder.video_path.stat().st_size, 3 * 480 * 270 * 3)

    def test_csv_is_closed_if_video_creation_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch('recording.AviWriter', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    SessionRecorder(folder)
            for path in Path(folder).iterdir():
                path.unlink()  # Windows rejects this if the file handle leaked.


class InterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = main.Console()
        cls.errors = []
        cls.app.report_callback_exception = lambda *args: cls.errors.append(args)
        cls.app.update()
        cls.app.after_cancel(cls.app.after_id)
        cls.app.after_id = None
        cls.folder = tempfile.TemporaryDirectory()
        cls.old_output = main.OUTPUT
        main.OUTPUT = Path(cls.folder.name)

    @classmethod
    def tearDownClass(cls):
        cls.app.close()
        main.OUTPUT = cls.old_output
        cls.folder.cleanup()
        if cls.errors:
            raise AssertionError(cls.errors)

    def setUp(self):
        self.app.new_session()
        self.app.inputs = InputGate()
        self.app.connect()
        self.app.camera.focus_force()
        self.app.update()

    def tick_once(self):
        app = self.app
        if app.after_id:
            app.after_cancel(app.after_id)
        app.last_tick = time.monotonic() - .1
        app.tick()
        app.after_cancel(app.after_id)
        app.after_id = None

    def test_space_stops_while_depth_entry_has_focus(self):
        app = self.app
        app.command_start('w')
        app.vehicle.hold = True
        app.depth_entry.focus_force()
        app.update()
        app.depth_entry.event_generate('<KeyPress-space>')
        app.update()
        self.assertFalse(app.vehicle.commands or app.vehicle.hold)
        app.depth_entry.event_generate('<KeyRelease-space>')
        app.command_start('w')
        self.assertFalse(app.vehicle.commands)
        app.command_end('w')
        app.command_start('w')
        self.assertEqual(app.vehicle.commands, {'w'})

    def test_invalid_depth_and_valid_comma_decimal(self):
        app = self.app
        for value in ('nan', 'inf', '-1', '1001', 'abc', ''):
            app.target.set(value)
            app.toggle_hold()
            self.assertFalse(app.vehicle.hold)
        app.target.set('121,5')
        app.toggle_hold()
        self.assertTrue(app.vehicle.hold)
        self.assertEqual(app.vehicle.target, 121.5)

    def test_emergency_disconnect_reconnect_stays_latched(self):
        app = self.app
        app.command_start('w')
        app.emergency_stop()
        app.connect()
        app.connect()
        self.assertTrue(app.vehicle.emergency)
        app.reset_emergency()
        app.command_start('w')
        self.assertFalse(app.vehicle.commands)
        app.command_end('w')
        app.command_start('w')
        self.assertEqual(app.vehicle.commands, {'w'})

    def test_focus_loss_stops_hold_and_manual_commands(self):
        app = self.app
        app.command_start('w')
        app.vehicle.hold = True
        with patch.object(app, 'focus_get', return_value=None):
            app.check_focus()
        self.assertFalse(app.vehicle.commands or app.vehicle.hold)

    def test_snapshot_and_recording_on_disconnect(self):
        app = self.app
        app.snapshot()
        photos = list(main.OUTPUT.glob('*.png'))
        self.assertTrue(photos)
        self.assertTrue(photos[-1].read_bytes().startswith(b'\x89PNG'))
        self.assertTrue(json.loads(photos[-1].with_suffix('.json').read_text())['synthetic'])
        app.toggle_record()
        recorder = app.recorder
        app.connect()
        self.assertFalse(app.recording)
        self.assertTrue(recorder.csv_file.closed and recorder.video.file.closed)

    def test_record_close_error_does_not_crash_interface(self):
        app = self.app
        app.toggle_record()
        recorder = app.recorder
        with patch.object(recorder, 'close', side_effect=OSError('disk full')):
            app.finish_record()
        self.assertFalse(app.recording)
        self.assertIn('Ошибка', app.notice.get())
        recorder.close()
        app.refresh()

    def test_all_training_steps_and_no_skipping(self):
        app = self.app
        app.training_next()
        self.assertEqual(app.lesson, 0)
        app.training_next()
        self.assertEqual(app.lesson, 0)
        app.connect()
        self.assertTrue(app.lesson_done)
        app.training_next()
        self.assertFalse(app.lesson_done)
        app.command_start('w')
        self.tick_once()
        app.command_end('w')
        self.assertTrue(app.lesson_done)
        app.training_next()
        app.stop()
        app.training_next()
        app.toggle_hold()
        for _ in range(20):
            app.vehicle.step(.25, .5)
        self.tick_once()
        self.assertTrue(app.lesson_done)
        app.training_next()
        app.snapshot()
        app.training_next()
        app.toggle_record()
        app.toggle_record()
        self.assertTrue(app.lesson_done)
        app.training_next()
        app.emergency_stop()
        app.training_next()
        app.reset_emergency()
        app.training_next()
        self.assertIsNone(app.lesson)
        self.assertEqual(app.progress['value'], 8)
        self.assertFalse(app.vehicle.commands or app.vehicle.hold)

    def test_small_window_keeps_emergency_and_training_visible(self):
        app = self.app
        app.training_next()
        app.connect()
        app.training_next()
        app.geometry('1000x700')
        app.update()
        self.assertGreaterEqual(app.camera.winfo_height(), 100)
        for widget in (app.panels['safety'], app.next_button, app.camera, app.record_button):
            self.assertGreater(widget.winfo_height(), 5)
            self.assertLess(widget.winfo_rooty() + widget.winfo_height(), app.winfo_rooty() + app.winfo_height() + 1)
        self.assertLessEqual(app.next_button.winfo_rooty() + app.next_button.winfo_height(), app.training_tab.winfo_rooty() + app.training_tab.winfo_height())
        app.geometry('1380x900')
        app.update()


if __name__ == '__main__':
    unittest.main(verbosity=2)

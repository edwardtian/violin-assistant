import sys
import math
import numpy as np
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QComboBox, QSlider, QPushButton, QLabel, QGridLayout,
)
from PyQt5.QtCore import Qt, QTimer, QRectF
from PyQt5.QtGui import QPainter, QColor, QFont, QPen, QBrush

from scales import get_scale_notes, midi_to_freq, SCALES
from pitch import yin
from audio import AudioCapture

NOTE_COLORS = {
    "correct": QColor(76, 175, 80),     # green
    "drift_yellow": QColor(255, 235, 59),  # yellow
    "drift_red": QColor(244, 67, 54),      # red
    "missed": QColor(158, 158, 158),       # gray
    "pending": QColor(33, 33, 33),         # dark (unplayed)
}

class NoteWidget(QWidget):
    def __init__(self, scale_notes, parent=None):
        super().__init__(parent)
        self.scale_notes = scale_notes
        self.n = len(scale_notes)
        self.colors = [NOTE_COLORS["pending"]] * self.n
        self.cursor_pos = 0.0  # 0..1 progress across the scale
        self.setMinimumHeight(200)
        self.setMinimumWidth(400)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        margin = 20
        note_h = 40
        note_gap = 4
        total_note_h = self.n * note_h + (self.n - 1) * note_gap
        start_y = margin + (h - 2 * margin - total_note_h) // 2

        # Draw each note block
        for i, (midi, name, freq) in enumerate(self.scale_notes):
            x = margin
            y = start_y + i * (note_h + note_gap)
            bw = w - 2 * margin
            color = self.colors[i]
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(QColor(100, 100, 100), 1))
            painter.drawRect(QRectF(x, y, bw, note_h))

            # Note name
            painter.setPen(QColor(255, 255, 255))
            font = QFont("Monospace", 14)
            painter.setFont(font)
            painter.drawText(QRectF(x + 8, y, 60, note_h), Qt.AlignVCenter, name)

        # Draw cursor
        cx = margin + self.cursor_pos * (w - 2 * margin)
        painter.setPen(QPen(QColor(255, 255, 255), 2))
        painter.drawLine(int(cx), margin, int(cx), h - margin)

        painter.end()

    def update_note(self, index, color_key):
        if 0 <= index < self.n:
            self.colors[index] = NOTE_COLORS[color_key]
            self.update()

    def reset_colors(self):
        self.colors = [NOTE_COLORS["pending"]] * self.n
        self.cursor_pos = 0.0
        self.update()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Violin Practice Assistant")
        self.setMinimumSize(800, 500)

        self.sr = 48000
        self.bpm = 60
        self.scale_name = "C Major"
        self.scale_notes = get_scale_notes(self.scale_name)
        self.current_note_index = -1
        self.elapsed_ms = 0

        self.audio = AudioCapture(sr=self.sr)
        self._build_ui()
        self._connect_signals()

        self.timer = QTimer()
        self.timer.setInterval(90)  # sync with audio chunk size
        self.timer.timeout.connect(self._tick)
        self.running = False

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(8)

        # Controls
        ctrl = QHBoxLayout()
        self.scale_combo = QComboBox()
        for name in SCALES:
            self.scale_combo.addItem(name)
        self.scale_combo.setCurrentText(self.scale_name)
        ctrl.addWidget(QLabel("Scale:"))
        ctrl.addWidget(self.scale_combo)

        self.bpm_slider = QSlider(Qt.Horizontal)
        self.bpm_slider.setRange(20, 200)
        self.bpm_slider.setValue(self.bpm)
        self.bpm_label = QLabel(f"{self.bpm} BPM")
        ctrl.addWidget(QLabel("BPM:"))
        ctrl.addWidget(self.bpm_slider)
        ctrl.addWidget(self.bpm_label)

        self.start_btn = QPushButton("Start")
        ctrl.addWidget(self.start_btn)
        layout.addLayout(ctrl)

        # Note visualization
        self.note_widget = NoteWidget(self.scale_notes)
        layout.addWidget(self.note_widget, 1)

        # Status readout
        self.status_label = QLabel("Not started — select scale and press Start")
        layout.addWidget(self.status_label)

    def _connect_signals(self):
        self.scale_combo.currentTextChanged.connect(self._on_scale_change)
        self.bpm_slider.valueChanged.connect(self._on_bpm_change)
        self.start_btn.clicked.connect(self._toggle)

    def _on_scale_change(self, name):
        self.scale_name = name
        self.scale_notes = get_scale_notes(name)
        self.note_widget.scale_notes = self.scale_notes
        self.note_widget.n = len(self.scale_notes)
        self.note_widget.reset_colors()
        self.current_note_index = -1
        self.elapsed_ms = 0

    def _on_bpm_change(self, val):
        self.bpm = val
        self.bpm_label.setText(f"{val} BPM")

    def _toggle(self):
        if self.running:
            self.stop()
        else:
            self.start()

    def start(self):
        try:
            self.audio.start()
        except Exception as e:
            self.status_label.setText(f"Mic error: {e}")
            return
        self.running = True
        self.start_btn.setText("Stop")
        self.note_widget.reset_colors()
        self.current_note_index = -1
        self.elapsed_ms = 0
        self.timer.start()

    def stop(self):
        self.running = False
        self.timer.stop()
        self.audio.stop()
        self.start_btn.setText("Start")
        self.status_label.setText("Stopped")

    def _tick(self):
        dt_ms = self.timer.interval()
        self.elapsed_ms += dt_ms

        # Calculate which note we should be on
        note_duration_ms = (60000 / self.bpm)  # ms per quarter note
        expected_index = int(self.elapsed_ms / note_duration_ms)
        n = len(self.scale_notes)

        # Update cursor
        total_duration = n * note_duration_ms
        self.note_widget.cursor_pos = min(self.elapsed_ms / total_duration, 1.0)
        self.note_widget.update()

        # If we've finished the scale
        if expected_index >= n:
            self.stop()
            self.status_label.setText("Scale complete!")
            return

        # Detect pitch
        chunk = self.audio.get_chunk()
        freq, conf = yin(chunk, sr=self.sr)

        target_midi = self.scale_notes[expected_index][0]
        target_freq = midi_to_freq(target_midi)

        if conf < 0.3 or freq <= 0:
            # No pitch detected — mark gray if we haven't already
            if self.current_note_index != expected_index:
                self.note_widget.update_note(expected_index, "missed")
                self.current_note_index = expected_index
            self.status_label.setText(
                f"No pitch detected — waiting for note {self.scale_notes[expected_index][1]}"
            )
            return

        # Compare detected pitch to target
        cents = round((12 * math.log2(freq / 440) - target_midi) * 100)

        if abs(cents) <= 10:
            color = "correct"
        elif abs(cents) <= 30:
            color = "drift_yellow"
        elif abs(cents) <= 50:
            color = "drift_red"
        else:
            color = "missed"

        if self.current_note_index != expected_index:
            self.note_widget.update_note(expected_index, color)
            self.current_note_index = expected_index

        # Update status
        target_name = self.scale_notes[expected_index][1]
        self.status_label.setText(
            f"🎵 {target_name}  |  Detected: {freq:.1f} Hz  |  "
            f"{'+' if cents > 0 else ''}{cents} cents  |  "
            f"conf: {conf:.0%}"
        )


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()

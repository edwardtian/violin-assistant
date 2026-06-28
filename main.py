import sys
import math
import numpy as np
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QComboBox, QSlider, QPushButton, QLabel, QScrollArea,
)
from PyQt5.QtCore import Qt, QTimer, QRectF, QRect, QSize
from PyQt5.QtGui import (
    QPainter, QColor, QFont, QPen, QBrush, QLinearGradient, QPainterPath,
)

from scales import get_full_scale_notes, midi_to_name, freq_to_midi, SCALES
from pitch import yin
from audio import AudioCapture

VISIBLE_SCALES = {
    k: v for k, v in SCALES.items()
    if k in ("C Major", "D Major", "A Major", "Bb Major", "G Major")
}

DEFAULT_GREEN_PCT = 5
DEFAULT_YELLOW_PCT = 20
DEFAULT_RED_PCT = 50

NOTE_COLORS = {
    "correct": QColor(76, 175, 80),
    "drift_yellow": QColor(255, 235, 59),
    "drift_red": QColor(244, 67, 54),
    "missed": QColor(158, 158, 158),
}

def cents_to_color(cents_abs, green_pct, yellow_pct, red_pct):
    if cents_abs <= green_pct:
        return NOTE_COLORS["correct"]
    elif cents_abs <= yellow_pct:
        return NOTE_COLORS["drift_yellow"]
    elif cents_abs <= red_pct:
        return NOTE_COLORS["drift_red"]
    else:
        return NOTE_COLORS["missed"]


class PitchReference(QWidget):
    """Right-side panel showing scale note segments and a live cursor square."""
    def __init__(self, scale_notes, parent=None):
        super().__init__(parent)
        self.scale_notes = scale_notes
        self.n = len(scale_notes)
        self.cursor_midi = None   # current detected midi
        self.setFixedWidth(80)
        self.setMinimumHeight(500)

    def set_cursor(self, midi):
        self.cursor_midi = midi
        self.update()

    def clear_cursor(self):
        self.cursor_midi = None
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()

        seg_h = h / self.n
        half = QColor(40, 40, 40)
        dark = QColor(25, 25, 25)

        for i, (midi, name, freq) in enumerate(self.scale_notes):
            y = i * seg_h
            color = half if i % 2 == 0 else dark
            painter.fillRect(QRectF(0, y, w, seg_h), QBrush(color))

            # Note name on the right
            painter.setPen(QColor(180, 180, 180))
            font = QFont("Monospace", 11)
            painter.setFont(font)
            painter.drawText(QRectF(2, y, w - 4, seg_h), Qt.AlignRight | Qt.AlignVCenter, name)

        # Draw cursor square if pitch detected
        if self.cursor_midi is not None:
            # Find which segment this midi falls in (or nearest)
            seg_idx = -1
            for i, (midi, _, _) in enumerate(self.scale_notes):
                if midi == self.cursor_midi:
                    seg_idx = i
                    break
            if seg_idx >= 0:
                cy = seg_idx * seg_h
                cs = seg_h
                # Semi-transparent square at the right side
                painter.setBrush(QColor(255, 255, 255, 60))
                painter.setPen(QPen(QColor(255, 255, 255, 100), 2))
                painter.drawRect(QRectF(w - cs, cy, cs, cs))

        painter.end()


class BarChart(QWidget):
    """Left-side horizontal scrolling bar chart of detected notes."""
    BAR_GAP = 4
    MIN_BAR_W = 16
    MAX_BAR_W = 100

    def __init__(self, scale_notes, parent=None):
        super().__init__(parent)
        self.scale_notes = scale_notes
        self.n = len(scale_notes)
        self.bars = []          # list of (midi, duration_ms, color)
        self._total_w = 600
        self.setMinimumHeight(500)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()
        seg_h = h / self.n

        # Background
        grad = QLinearGradient(0, h, 0, 0)
        grad.setColorAt(0, QColor(20, 20, 20))
        grad.setColorAt(1, QColor(40, 40, 40))
        painter.fillRect(QRect(0, 0, w, h), QBrush(grad))

        # Draw bars
        x = 0
        for midi, dur, color in self.bars:
            bw = self._bar_width(dur)
            # Find segment index for this midi
            seg_idx = -1
            for i, (m, _, _) in enumerate(self.scale_notes):
                if m == midi:
                    seg_idx = i
                    break
            if seg_idx < 0:
                x += bw + self.BAR_GAP
                continue

            y = seg_idx * seg_h
            bh = seg_h - 2  # slight gap from segment border

            rect = QRectF(x, y + 1, bw, bh)
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(QColor(100, 100, 100), 1))
            painter.drawRect(rect)

            x += bw + self.BAR_GAP

        painter.end()

    def _bar_width(self, duration_ms):
        w = int(duration_ms / 20)
        return max(self.MIN_BAR_W, min(w, self.MAX_BAR_W))

    def add_bar(self, midi, duration_ms, color):
        self.bars.append((midi, duration_ms, color))
        tw = sum(self._bar_width(d) + self.BAR_GAP for _, d, _ in self.bars)
        self._total_w = max(tw, 600)
        self.setMinimumWidth(self._total_w)
        self.update()

    def reset(self):
        self.bars.clear()
        self._total_w = 600
        self.setMinimumWidth(600)
        self.update()

    def minimumSizeHint(self):
        return QSize(self._total_w, 500)

    def sizeHint(self):
        return QSize(self._total_w, 500)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Violin Practice Assistant")
        self.setMinimumSize(900, 650)

        self.sr = 48000
        self.bpm = 60
        self.scale_name = "C Major"
        self.scale_notes = get_full_scale_notes(self.scale_name)

        self.green_pct = DEFAULT_GREEN_PCT
        self.yellow_pct = DEFAULT_YELLOW_PCT
        self.red_pct = DEFAULT_RED_PCT

        # Note accumulation
        self.current_bar = None
        self.current_bar_start_ms = 0
        self.current_bar_midi = 0
        self.current_bar_cents = 0.0
        self.consecutive_silence = 0
        self.silence_threshold = 3

        self.audio = AudioCapture(sr=self.sr)
        self._build_ui()
        self._connect_signals()

        self.timer = QTimer()
        self.timer.setInterval(90)
        self.timer.timeout.connect(self._tick)
        self.running = False

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(6)

        # Controls
        ctrl = QHBoxLayout()
        self.scale_combo = QComboBox()
        for name in VISIBLE_SCALES:
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

        ctrl.addWidget(QLabel("G≤"))
        self.green_slider = QSlider(Qt.Horizontal)
        self.green_slider.setRange(1, 50)
        self.green_slider.setValue(self.green_pct)
        self.green_slider.setFixedWidth(80)
        self.green_label = QLabel(f"{self.green_pct}¢")
        ctrl.addWidget(self.green_slider)
        ctrl.addWidget(self.green_label)

        ctrl.addWidget(QLabel("Y≤"))
        self.yellow_slider = QSlider(Qt.Horizontal)
        self.yellow_slider.setRange(1, 50)
        self.yellow_slider.setValue(self.yellow_pct)
        self.yellow_slider.setFixedWidth(80)
        self.yellow_label = QLabel(f"{self.yellow_pct}¢")
        ctrl.addWidget(self.yellow_slider)
        ctrl.addWidget(self.yellow_label)

        ctrl.addWidget(QLabel("R≤"))
        self.red_slider = QSlider(Qt.Horizontal)
        self.red_slider.setRange(1, 100)
        self.red_slider.setValue(self.red_pct)
        self.red_slider.setFixedWidth(80)
        self.red_label = QLabel(f"{self.red_pct}¢")
        ctrl.addWidget(self.red_slider)
        ctrl.addWidget(self.red_label)
        layout.addLayout(ctrl)

        # Main area: bar chart (left) + pitch reference (right)
        hsplit = QHBoxLayout()
        self.bar_chart = BarChart(self.scale_notes)
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.bar_chart)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        hsplit.addWidget(self.scroll, 1)

        self.pitch_ref = PitchReference(self.scale_notes)
        hsplit.addWidget(self.pitch_ref)
        layout.addLayout(hsplit, 1)

        # Big note display
        self.big_note_label = QLabel("—")
        self.big_note_label.setAlignment(Qt.AlignCenter)
        font = QFont("Monospace", 48)
        self.big_note_label.setFont(font)
        self.big_note_label.setStyleSheet("color: white; background-color: #1a1a1a; padding: 6px;")
        layout.addWidget(self.big_note_label)

        # Status
        self.status_label = QLabel("Select scale, set BPM, press Start")
        layout.addWidget(self.status_label)

    def _connect_signals(self):
        self.scale_combo.currentTextChanged.connect(self._on_scale_change)
        self.bpm_slider.valueChanged.connect(self._on_bpm_change)
        self.start_btn.clicked.connect(self._toggle)
        self.green_slider.valueChanged.connect(self._on_green_change)
        self.yellow_slider.valueChanged.connect(self._on_yellow_change)
        self.red_slider.valueChanged.connect(self._on_red_change)

    def _on_scale_change(self, name):
        self.scale_name = name
        self.scale_notes = get_full_scale_notes(name)
        self.bar_chart.scale_notes = self.scale_notes
        self.bar_chart.n = len(self.scale_notes)
        self.bar_chart.reset()
        self.pitch_ref.scale_notes = self.scale_notes
        self.pitch_ref.n = len(self.scale_notes)
        self.pitch_ref.clear_cursor()

    def _on_bpm_change(self, val):
        self.bpm = val
        self.bpm_label.setText(f"{val} BPM")

    def _on_green_change(self, val):
        self.green_pct = val
        self.green_label.setText(f"{val}¢")

    def _on_yellow_change(self, val):
        self.yellow_pct = val
        self.yellow_label.setText(f"{val}¢")

    def _on_red_change(self, val):
        self.red_pct = val
        self.red_label.setText(f"{val}¢")

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
        self.bar_chart.reset()
        self.pitch_ref.clear_cursor()
        self.current_bar = None
        self.consecutive_silence = 0
        self.elapsed_ms = 0
        self.timer.start()

    def stop(self):
        self.running = False
        self.timer.stop()
        self.audio.stop()
        self.start_btn.setText("Start")
        self.status_label.setText("Stopped")
        self.pitch_ref.clear_cursor()
        self._close_bar()

    def _close_bar(self):
        if self.current_bar is not None:
            elapsed = self.elapsed_ms - self.current_bar_start_ms
            color = cents_to_color(
                abs(self.current_bar_cents), self.green_pct, self.yellow_pct, self.red_pct
            )
            self.bar_chart.add_bar(self.current_bar_midi, elapsed, color)
            QTimer.singleShot(0, self._scroll_to_end)
        self.current_bar = None

    def _scroll_to_end(self):
        sb = self.scroll.horizontalScrollBar()
        sb.setValue(sb.maximum())

    def _tick(self):
        dt_ms = self.timer.interval()
        self.elapsed_ms += dt_ms

        chunk = self.audio.get_chunk()
        freq, conf = yin(chunk, sr=self.sr)

        if conf >= 0.3 and freq > 0:
            self.consecutive_silence = 0
            midi_i, cents = freq_to_midi(freq)
            note_name = midi_to_name(midi_i)

            # Update cursor
            self.pitch_ref.set_cursor(midi_i)

            if self.current_bar is not None and self.current_bar_midi == midi_i:
                self.current_bar_cents = (self.current_bar_cents * 0.7) + (cents * 0.3)
            else:
                self._close_bar()
                self.current_bar_midi = midi_i
                self.current_bar_cents = cents
                self.current_bar_start_ms = self.elapsed_ms
                self.current_bar = "active"

            # Status
            self.status_label.setText(
                f"{note_name}  {freq:.1f} Hz  "
                f"{'+' if cents > 0 else ''}{cents:.0f}¢  "
                f"conf:{conf:.0%}"
            )

            # Big note display
            color = cents_to_color(abs(cents), self.green_pct, self.yellow_pct, self.red_pct)
            self.big_note_label.setText(note_name)
            self.big_note_label.setStyleSheet(
                f"color: {color.name()}; background-color: #1a1a1a; padding: 6px;"
            )
        else:
            self.consecutive_silence += 1
            if self.consecutive_silence >= self.silence_threshold:
                self._close_bar()
                self.pitch_ref.clear_cursor()
            self.status_label.setText("Silence — waiting...")
            self.big_note_label.setText("—")
            self.big_note_label.setStyleSheet(
                "color: white; background-color: #1a1a1a; padding: 6px;"
            )


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()

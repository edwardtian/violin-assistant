import sys
import math
import numpy as np
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QComboBox, QSlider, QPushButton, QLabel, QScrollArea,
)
from PyQt5.QtCore import Qt, QTimer, QRectF, QRect, QSize
from PyQt5.QtGui import QPainter, QColor, QFont, QPen, QBrush, QLinearGradient

from scales import get_scale_notes, midi_to_name, freq_to_midi, SCALES
from pitch import yin
from audio import AudioCapture

# Only keep the requested scales
VISIBLE_SCALES = {
    k: v for k, v in SCALES.items()
    if k in ("C Major", "D Major", "A Major", "Bb Major", "G Major")
}

# Default color thresholds (percent of a semitone = cents)
# Green: <= green_pct% of semitone (100 cents)
# Yellow: <= yellow_pct%
# Red: <= red_pct%
# Beyond red: gray (missed)
DEFAULT_GREEN_PCT = 5
DEFAULT_YELLOW_PCT = 20
DEFAULT_RED_PCT = 50

NOTE_COLORS = {
    "correct": QColor(76, 175, 80),     # green
    "drift_yellow": QColor(255, 235, 59),  # yellow
    "drift_red": QColor(244, 67, 54),      # red
    "missed": QColor(158, 158, 158),       # gray
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

class BarData:
    """One detected note event."""
    def __init__(self, midi, note_name, freq, cents, duration_ms, green_pct, yellow_pct, red_pct):
        self.midi = midi
        self.note_name = note_name
        self.freq = freq
        self.cents = cents
        self.duration_ms = duration_ms
        self.color = cents_to_color(abs(cents), green_pct, yellow_pct, red_pct)

class BarChart(QWidget):
    """Horizontal scrolling bar chart of detected notes."""
    MIN_BAR_W = 20
    MAX_BAR_W = 120
    HEIGHT_SCALE = 3.0      # pixels per MIDI step
    MIDI_MIN = 55           # G3 — violin lowest
    MIDI_MAX = 88           # E7 — violin highest
    BAR_GAP = 2
    LABEL_MARGIN = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bars = []          # list of BarData
        self._total_w = 400
        self.setMinimumHeight(300)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()

        # Background
        grad = QLinearGradient(0, h, 0, 0)
        grad.setColorAt(0, QColor(20, 20, 20))
        grad.setColorAt(1, QColor(40, 40, 40))
        painter.fillRect(QRect(0, 0, w, h), QBrush(grad))

        # Draw bars
        x = 0
        for bar in self.bars:
            bw = self._bar_width(bar.duration_ms)
            bh = self._bar_height(bar.midi, h)
            by = h - bh - 20
            if by < 0:
                by = 0

            rect = QRectF(x, by, bw, bh)
            painter.setBrush(QBrush(bar.color))
            painter.setPen(QPen(QColor(100, 100, 100), 1))
            painter.drawRect(rect)

            painter.setPen(QColor(255, 255, 255))
            font = QFont("Monospace", 10)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignCenter, bar.note_name)

            x += bw + self.BAR_GAP

        painter.end()

    def _bar_width(self, duration_ms):
        w = int(duration_ms / 20)
        return max(self.MIN_BAR_W, min(w, self.MAX_BAR_W))

    def _bar_height(self, midi, height):
        ratio = (midi - self.MIDI_MIN) / (self.MIDI_MAX - self.MIDI_MIN)
        return int(ratio * (height - 60)) + 10

    def add_bar(self, bar):
        self.bars.append(bar)
        tw = sum(self._bar_width(b.duration_ms) + self.BAR_GAP for b in self.bars)
        self._total_w = max(tw, 400)
        self.setMinimumWidth(self._total_w)
        self.update()

    def reset(self):
        self.bars.clear()
        self._total_w = 400
        self.setMinimumWidth(400)
        self.update()

    def minimumSizeHint(self):
        return QSize(self._total_w, 300)

    def sizeHint(self):
        return QSize(self._total_w, 300)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Violin Practice Assistant")
        self.setMinimumSize(800, 550)

        self.sr = 48000
        self.bpm = 60
        self.scale_name = "C Major"
        self.scale_notes = get_scale_notes(self.scale_name)

        # Color thresholds (in cents)
        self.green_pct = DEFAULT_GREEN_PCT
        self.yellow_pct = DEFAULT_YELLOW_PCT
        self.red_pct = DEFAULT_RED_PCT

        # Note accumulation
        self.current_bar = None        # BarData being built
        self.current_bar_start_ms = 0
        self.current_bar_midi = 0
        self.current_bar_note = ""
        self.current_bar_freq = 0.0
        self.current_bar_cents = 0.0
        self.current_bar_conf = 0.0
        self.consecutive_silence = 0
        self.silence_threshold = 3      # ticks before closing a bar

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

        # ---- Controls ----
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

        # Color threshold sliders
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

        # ---- Scrollable bar chart ----
        self.bar_chart = BarChart()
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.bar_chart)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layout.addWidget(self.scroll, 1)

        # ---- Status ----
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
        self.scale_notes = get_scale_notes(name)

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
        # Flush current bar if any
        if self.current_bar is not None:
            self._close_bar()

    def _close_bar(self):
        """Finalize current bar and add to chart."""
        if self.current_bar is not None:
            elapsed = self.elapsed_ms - self.current_bar_start_ms
            bar = BarData(
                self.current_bar_midi,
                self.current_bar_note,
                self.current_bar_freq,
                self.current_bar_cents,
                elapsed,
                self.green_pct, self.yellow_pct, self.red_pct,
            )
            self.bar_chart.add_bar(bar)
            # Auto-scroll to newest
            self.scroll.ensureWidgetVisible(self.bar_chart, x=1.0, y=0.0)
        self.current_bar = None

    def _tick(self):
        dt_ms = self.timer.interval()
        self.elapsed_ms += dt_ms

        chunk = self.audio.get_chunk()
        freq, conf = yin(chunk, sr=self.sr)

        # ---- Pitch detected ----
        if conf >= 0.3 and freq > 0:
            self.consecutive_silence = 0
            midi_i, cents = freq_to_midi(freq)
            note_name = midi_to_name(midi_i)

            # If same note as current bar, just extend it
            if self.current_bar is not None and self.current_bar_midi == midi_i:
                # Update running cents average
                self.current_bar_cents = (self.current_bar_cents * 0.7) + (cents * 0.3)
                self.current_bar_freq = freq
                self.current_bar_conf = conf
                # Don't add a new bar — just wait for close
            else:
                # Note changed — close previous bar, start new one
                self._close_bar()
                self.current_bar_midi = midi_i
                self.current_bar_note = note_name
                self.current_bar_freq = freq
                self.current_bar_cents = cents
                self.current_bar_conf = conf
                self.current_bar_start_ms = self.elapsed_ms
                self.current_bar = "active"  # non-None sentinel

            # Status update
            self.status_label.setText(
                f"{note_name}  {freq:.1f} Hz  "
                f"{'+' if cents > 0 else ''}{cents:.0f}¢  "
                f"conf:{conf:.0%}"
            )
        else:
            # No pitch
            self.consecutive_silence += 1
            if self.consecutive_silence >= self.silence_threshold:
                self._close_bar()
            self.status_label.setText(
                f"Silence — waiting..."
            )


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()

import sounddevice as sd
import numpy as np
from threading import Lock

class AudioCapture:
    def __init__(self, sr=48000, chunk_ms=90, channels=1):
        self.sr = sr
        self.chunk_size = int(sr * chunk_ms / 1000)
        self.channels = channels
        self._buffer = np.zeros(self.chunk_size * 4, dtype=np.float32)
        self._lock = Lock()
        self._stream = None
        self._running = False

    def _callback(self, indata, frames, time, status):
        with self._lock:
            self._buffer = np.roll(self._buffer, -frames)
            self._buffer[-frames:] = indata[:, 0] if indata.ndim > 1 else indata

    def start(self):
        try:
            self._stream = sd.InputStream(
                samplerate=self.sr,
                channels=self.channels,
                callback=self._callback,
                blocksize=self.chunk_size,
            )
            self._stream.start()
            self._running = True
        except Exception as e:
            self._running = False
            raise e

    def stop(self):
        self._running = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def get_chunk(self):
        with self._lock:
            return self._buffer[-self.chunk_size:].copy()

    @property
    def running(self):
        return self._running

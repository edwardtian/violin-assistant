import math

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

def midi_to_name(midi):
    octave = (midi // 12) - 1
    note = midi % 12
    return NOTE_NAMES[note] + str(octave)

def midi_to_freq(midi):
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))

def freq_to_midi(freq):
    if freq <= 0:
        return 0, 0.0
    midi = 12 * math.log2(freq / 440.0) + 69
    midi_i = round(midi)
    cents = (midi - midi_i) * 100
    return midi_i, cents

SCALES = {
    "C Major":    [60, 62, 64, 65, 67, 69, 71, 72],   # C4-D4-E4-F4-G4-A4-B4-C5
    "G Major":    [67, 69, 71, 72, 74, 76, 78, 79],   # G4-A4-B4-C5-D5-E5-F#5-G5
    "D Major":    [62, 64, 66, 67, 69, 71, 73, 74],   # D4-E4-F#4-G4-A4-B4-C#5-D5
    "A Major":    [69, 71, 73, 74, 76, 78, 80, 81],   # A4-B4-C#5-D5-E5-F#5-G#5-A5
    "E Major":    [64, 66, 68, 69, 71, 73, 75, 76],   # E4-F#4-G#4-A4-B4-C#5-D#5-E5
    "F Major":    [65, 67, 69, 70, 72, 74, 76, 77],   # F4-G4-A4-Bb4-C5-D5-E5-F5
    "Bb Major":   [70, 72, 74, 75, 77, 79, 81, 82],   # Bb4-C5-D5-Eb5-F5-G5-A5-Bb5
    "a minor":    [69, 71, 72, 74, 76, 77, 79, 81],   # A4-B4-C5-D5-E5-F5-G5-A5
    "d minor":    [62, 64, 65, 67, 69, 70, 72, 74],   # D4-E4-F4-G4-A4-Bb4-C5-D5
    "g minor":    [67, 69, 70, 72, 74, 75, 77, 79],   # G4-A4-Bb4-C5-D5-Eb5-F5-G5
    "C Chromatic": [60,61,62,63,64,65,66,67,68,69,70,71,72],
}

def get_scale_notes(scale_name):
    mids = SCALES[scale_name]
    return [(m, midi_to_name(m), midi_to_freq(m)) for m in mids]

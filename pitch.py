import numpy as np

def yin(signal, sr=44100, threshold=0.15, min_freq=65, max_freq=2100):
    """YIN pitch detection algorithm. Returns (frequency, confidence).
    
    Uses the global minimum of the normalized difference function rather
    than the first dip below threshold for better robustness.
    """
    signal = signal.astype(np.float64)
    signal = signal * np.hanning(len(signal))
    n = len(signal)
    if n < 256:
        return 0.0, 0.0

    max_lag = int(sr / min_freq)
    min_lag = int(sr / max_freq)
    if max_lag > n:
        max_lag = n
    if min_lag < 1:
        min_lag = 1

    # Autocorrelation via FFT
    nfft = 1 << (2 * n - 1).bit_length()
    fft = np.fft.rfft(signal, nfft)
    acf = np.fft.irfft(np.abs(fft) ** 2, nfft)[:max_lag]
    if len(acf) < max_lag:
        return 0.0, 0.0

    # Difference function: d[τ] = acf[0] - acf[τ]
    d = np.zeros(max_lag)
    d[0] = acf[0]
    for tau in range(1, max_lag):
        d[tau] = acf[0] - acf[tau]

    # Cumulative mean squared normalized difference
    d_norm = np.ones(max_lag)
    running = 0.0
    for tau in range(1, max_lag):
        running += d[tau]
        if running > 0:
            d_norm[tau] = d[tau] * tau / running
        else:
            d_norm[tau] = 1.0

    # Find first local minimum below threshold
    lag = 0
    for tau in range(min_lag + 1, max_lag - 1):
        if d_norm[tau] < threshold and d_norm[tau] < d_norm[tau - 1] and d_norm[tau] < d_norm[tau + 1]:
            lag = tau
            break

    if lag == 0:
        return 0.0, 0.0

    # Parabolic interpolation
    if lag > 1 and lag < max_lag - 1:
        a = d_norm[lag - 1]
        b = d_norm[lag]
        c = d_norm[lag + 1]
        denom = a + c - 2 * b
        if denom != 0:
            lag = lag + (c - a) / (2 * denom)

    freq = sr / lag
    confidence = 1.0 - d_norm[int(round(lag))]

    if freq < min_freq or freq > max_freq:
        return 0.0, 0.0
    return freq, confidence

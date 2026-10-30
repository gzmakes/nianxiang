"""Conservative, fixed count-unit QC; same causal window filter in train and replay."""
import numpy as np
from scipy.signal import butter, sosfilt, sosfilt_zi
from src.config import CONFIG

def quality_check(x, signal_quality=0, config=None):
    c = config or CONFIG
    x = np.asarray(x, dtype=float)
    reasons = []
    if len(x) < int(c['fs']*c['window_s']): reasons.append('short_window')
    if not np.isfinite(signal_quality) or signal_quality > c['quality_max']: reasons.append('poor_contact')
    if not np.isfinite(x).all(): reasons.append('nonfinite')
    elif len(x):
        if np.std(x) < 1: reasons.append('flatline')
        if np.max(np.abs(x)) > c['max_abs_counts']: reasons.append('large_amplitude')
        if np.ptp(x) > c['max_peak_to_peak']: reasons.append('large_range')
        if len(x)>1 and np.max(np.abs(np.diff(x))) > c['max_step_counts']: reasons.append('abrupt_step')
    return not reasons, reasons

def preprocess(x, config=None):
    c = config or CONFIG
    x = np.asarray(x, dtype=float)
    if not np.isfinite(x).all(): raise ValueError('Nonfinite EEG')
    sos = butter(c['filter_order'], c['bandpass'], fs=c['fs'], btype='bandpass', output='sos')
    y, _ = sosfilt(sos, x, zi=sosfilt_zi(sos)*x[0])
    return y

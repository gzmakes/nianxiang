from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABELS = ['Eyes-closed rest', 'Medium arithmetic', 'Hard arithmetic']
COLORS = ['#50dbc0', '#8199ff', '#f4ba68']
CONFIG = dict(fs=512, window_s=4, step_s=2, bandpass=[1, 40],
              filter_order=4, filter_mode='causal_sos_reset_each_4s_window',
              notch=None, unit='device counts; physical units unconfirmed',
              fs_status='nominal MindWave 512 Hz; exact timing not independently verified',
              quality_max=0, max_abs_counts=1500, max_peak_to_peak=2500,
              max_step_counts=600, seed=42)

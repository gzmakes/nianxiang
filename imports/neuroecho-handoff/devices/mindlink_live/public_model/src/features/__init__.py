import numpy as np
from scipy.signal import welch
from src.config import CONFIG

BANDS = {'delta':(1,4), 'theta':(4,8), 'alpha':(8,13), 'beta':(13,30)}

def extract_features(filtered, fs=CONFIG['fs']):
    x = np.asarray(filtered, dtype=float)
    f, p = welch(x, fs=fs, nperseg=min(len(x),int(fs*2)))
    mask = (f>=1)&(f<=40)
    total = np.trapz(p[mask],f[mask]) + 1e-12
    out = {}
    for name,(lo,hi) in BANDS.items():
        m=(f>=lo)&(f<hi)
        power = np.trapz(p[m],f[m]) + 1e-12
        out['log_'+name] = float(np.log10(power))
        out['relative_'+name] = float(power/total)
    out['log_theta_beta'] = out['log_theta']-out['log_beta']
    out['log_alpha_beta'] = out['log_alpha']-out['log_beta']
    out['log_rms'] = float(np.log10(np.sqrt(np.mean(x*x))+1e-12))
    out['log_variance'] = float(np.log10(np.var(x)+1e-12))
    q = p[mask]/(p[mask].sum()+1e-12)
    out['spectral_entropy'] = float(-np.sum(q*np.log2(q+1e-12))/np.log2(len(q)))
    return out

FEATURES = list(extract_features(np.sin(np.arange(2048)/10)))

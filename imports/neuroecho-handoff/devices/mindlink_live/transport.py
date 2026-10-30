import os, select
try:
    import serial
    if not hasattr(serial, 'Serial'): raise ImportError('pyserial unavailable')
except ImportError:
    if os.name == 'nt':
        raise RuntimeError('Install pyserial in the current Python environment: python -m pip install pyserial')
    # Linux fallback uses the same OS serial interface as the verified probe.
    import termios, fcntl, types
    class NativeSerial:
        def __init__(self, port, baud, timeout=.2, exclusive=True):
            self.fd=os.open(port,os.O_RDWR|os.O_NOCTTY|os.O_NONBLOCK)
            try:
                fcntl.flock(self.fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                self.old=termios.tcgetattr(self.fd);a=termios.tcgetattr(self.fd)
                a[0]=0;a[1]=0;a[2]=termios.CS8|termios.CREAD|termios.CLOCAL;a[3]=0
                a[4]=termios.B57600;a[5]=termios.B57600;a[6][termios.VMIN]=0;a[6][termios.VTIME]=0
                termios.tcsetattr(self.fd,termios.TCSANOW,a)
                self.timeout=timeout
            except Exception:
                os.close(self.fd);raise
        @property
        def in_waiting(self):return 8192
        def read(self,n):
            if not select.select([self.fd],[],[],self.timeout)[0]:return b''
            data=os.read(self.fd,n)
            if not data:raise OSError('USB disconnected')
            return data
        def __enter__(self):return self
        def __exit__(self,*args):
            try:termios.tcsetattr(self.fd,termios.TCSANOW,self.old)
            finally:os.close(self.fd)
    serial=types.SimpleNamespace(Serial=NativeSerial,SerialException=OSError)


def open_serial(port):
    options = dict(port=port, baudrate=57600, timeout=.2)
    if os.name != 'nt': options['exclusive'] = True
    if getattr(serial, 'Serial', None) is globals().get('NativeSerial'):
        return NativeSerial(port,57600,timeout=.2)
    return serial.Serial(**options)

def list_ports():
    try:
        from serial.tools.list_ports import comports
        return [{'port':p.device,'description':p.description,'vid':p.vid,'pid':p.pid} for p in comports()]
    except ImportError:
        from pathlib import Path
        return [{'port':str(p),'description':'USB serial','vid':None,'pid':None} for p in Path('/dev').glob('ttyUSB*')]

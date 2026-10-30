"""Standard-library client: usable on Windows/Linux, no serial access required."""
import json,time,urllib.request
class MindLinkClient:
    def __init__(self,url='http://127.0.0.1:8876',source='esense'):
        if source not in ('esense','personal'):raise ValueError('Unknown source')
        self.url=url.rstrip('/');self.source=source
    def state(self):
        with urllib.request.urlopen(self.url+'/api/v1/state?source='+self.source,timeout=2) as r:return json.load(r)
    def attention(self):
        s=self.state();a=s['attention']
        return a['value'] if s['live'] and a['valid'] and a['age_ms'] is not None and a['age_ms']<=2500 else None
if __name__=='__main__':
    c=MindLinkClient();since=None;shown=False
    while True:
        try:value=c.attention()
        except (OSError,ValueError):value=None
        if value is None:since=None;shown=False;print('HIDE_CONTENT');print('signal unavailable')
        else:
            if value>=60:
                since=since or time.monotonic()
                if not shown and time.monotonic()-since>=2:shown=True;print('SHOW_CONTENT')
            elif value<45:since=None;shown=False;print('HIDE_CONTENT')
            else:since=None
            print('attention:',value)
        time.sleep(.25)

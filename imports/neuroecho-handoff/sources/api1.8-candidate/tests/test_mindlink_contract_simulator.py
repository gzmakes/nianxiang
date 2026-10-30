"""Exercise the actual HTTP-adapter contract against an in-process fake service.

No device, recording, network listener, or personal data is involved.
"""
import json
import time
from http.client import IncompleteRead
from unittest.mock import patch

import pytest
from server import mindlink


def metrics(source='esense'):
    return {'api_version':'1.0', 'session_id':'synthetic', 'sequence':1,
            'timestamp_unix':time.time(), 'connected':True, 'live':True, 'signal_quality':0,
            'attention':{'value':62, 'valid':True, 'source': 'personal_model' if source == 'personal' else 'neurosky_esense',
                         'age_ms':50, 'updated_at_unix':time.time()-0.05, 'reason':None, 'unit':'score_0_100', 'model':None},
            'relaxation':{'value':None,'valid':False,'source':'neurosky_esense','age_ms':None,'reason':'unavailable'},
            'capabilities':{'personal_model_loaded':source == 'personal', 'emotion_model_loaded':False}}


class SyntheticService:
    def __init__(self, response): self.response = response; self.requests=[]
    def open(self, request, timeout):
        self.requests.append((request.full_url, timeout, request.get_header('Cache-control')))
        return self
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, limit):
        if isinstance(self.response, Exception): raise self.response
        return self.response if isinstance(self.response, bytes) else json.dumps(self.response).encode()


def read(service, **kwargs):
    with patch.object(mindlink, 'build_opener', return_value=service):
        return mindlink.read_attention(**kwargs)


def test_real_fetch_path_is_opt_in_and_offline_always_withdraws_score():
    service = SyntheticService(metrics())
    assert read(service)['reason'] == 'not_enabled' and service.requests == []
    result = read(service, enabled=True)
    assert result['available'] and result['score'] == 62
    assert service.requests == [('http://127.0.0.1:8876/api/v1/state?source=esense', 1.0, 'no-store')]
    service.response = IncompleteRead(b'incomplete')
    assert read(service, enabled=True)['score'] is None
    service.response = metrics(); service.response['connected'] = False
    assert read(service, enabled=True)['reason'] == 'signal_not_live'


def test_personal_source_requires_matching_loaded_model_and_never_falls_back():
    service = SyntheticService(metrics('personal'))
    service.response['attention']['value'] = 0
    personal = read(service, enabled=True, source='personal')
    assert personal['available'] and personal['score'] == 0 and personal['source'] == 'personal_model'
    assert service.requests[-1][0].endswith('?source=personal')
    service.response = metrics('esense')
    unavailable = read(service, enabled=True, source='personal')
    assert not unavailable['available'] and unavailable['source'] == 'personal_model' and unavailable['score'] is None
    service.response = metrics('personal'); service.response['capabilities']['personal_model_loaded'] = False
    assert not read(service, enabled=True, source='personal')['available']
    before = len(service.requests)
    assert read(service, enabled=True, source='http://elsewhere')['reason'] == 'unsupported_source'
    assert len(service.requests) == before


def test_updated_at_freshness_cannot_be_hidden_by_reported_age():
    service = SyntheticService(metrics())
    service.response['attention']['updated_at_unix'] = time.time() - 3
    assert not read(service, enabled=True)['available']
    service.response['attention']['updated_at_unix'] = time.time() + 30
    assert not read(service, enabled=True)['available']
    service.response['attention']['updated_at_unix'] = float('nan')
    assert not read(service, enabled=True)['available']


@pytest.mark.parametrize('body', [b'{broken', b'a'*65537])
def test_malformed_or_oversize_response_is_unavailable(body):
    assert read(SyntheticService(body), enabled=True)['reason'] == 'service_unavailable'

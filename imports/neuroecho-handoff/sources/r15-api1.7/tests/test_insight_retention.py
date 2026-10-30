import json

from server import insight_ai


def test_enrichment_does_not_retain_source_snapshots_between_requests():
    class FakeModel:
        def __init__(self):
            self.calls = 0

        def complete(self, *args, **kwargs):
            self.calls += 1
            return json.dumps({
                'facts': ['一条待确认事实'],
                'insights': [
                    {'type': 'pattern', 'title': '观察', 'text': '候选'},
                    {'type': 'risk', 'title': '风险', 'text': '候选'},
                    {'type': 'opportunity', 'title': '选择', 'text': '候选'},
                ],
            }, ensure_ascii=False)

    source = {'ok': True, 'connector': {'id': 'test', 'name': '测试'},
              'items': [{'title': '合成标题', 'summary': '合成内容'}]}
    client = FakeModel()
    assert insight_ai.enrich(source, client)['ai_generated'] is True
    assert insight_ai.enrich(source, client)['ai_generated'] is True
    assert client.calls == 2
    assert not hasattr(insight_ai, '_CACHE')


def test_metadata_only_does_not_infer_user_habits_or_call_model():
    class NoModel:
        def complete(self,*args,**kwargs): raise AssertionError('metadata must remain literal')
    source={'ok':True,'connector':{'id':'git','name':'本地代码库'},
            'items':[{'title':'合成提交','meta':'仓库名 · abc123 · today','summary':'只是一条提交标题'}],
            'understanding':{'facts':['合成提交（仓库名 · abc123 · today）'],'inferences':['不可靠的旧推测']}}
    result=insight_ai.enrich(source,NoModel())
    assert result['understanding']['facts']==source['understanding']['facts']
    assert result['understanding']['inferences']==[]
    assert len(result['insights'])==1 and result['ai_generated'] is False
    assert '习惯' not in result['insights'][0]['text']


def test_model_invented_fact_cannot_replace_literal_source_fact():
    class Invented:
        def complete(self,*args,**kwargs):
            return json.dumps({'facts':['用户是这个项目的作者，长期偏好大提交'],
                               'inferences':[], 'questions':['想聊哪一段？'], 'insights':[]})
    result=insight_ai.enrich({'ok':True,'connector':{'id':'notion'},
                             'items':[{'title':'计划草稿','summary':'一段原文'}],
                             'understanding':{'facts':['文档原话：今天先整理草稿']}},Invented())
    assert result['understanding']['facts']==['文档原话：今天先整理草稿']
    assert len(result['insights'])==1

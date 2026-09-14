import sys, json, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from providers import build_request, parse_provider_response, ollama_base, decode_text
from core import DEFAULTS, build_payload

class ProviderTests(unittest.TestCase):
    def test_url_validation_and_no_redirect_credentials_in_query(self):
        for url in ('file:///tmp', 'http://user:pass@host', 'http://host?key=secret', 'http://host/api/chat', 'http://host:abc'):
            with self.assertRaises(ValueError): ollama_base(url)
        self.assertEqual(ollama_base('http://localhost:11434/'), 'http://localhost:11434')
        payload = build_payload(DEFAULTS, [{'role':'user','content':'hello'}])
        for p in ('openai','gemini','claude','vercel'):
            url, headers, body = build_request(p,'fake-key',payload)
            self.assertNotIn('fake-key',url)
            self.assertNotIn('fake-key',json.dumps(body))
            self.assertTrue(url.startswith('https://'))

    def test_reasoning_blocks_are_not_displayed(self):
        self.assertEqual(parse_provider_response('claude', {'content':[
            {'type':'thinking','thinking':'internal'}, {'type':'text','text':'보이는 답변'}]})[0], '보이는 답변')
        self.assertEqual(parse_provider_response('gemini', {'candidates':[{'content':{'parts':[
            {'thought':True,'text':'internal'}, {'text':'보이는 답변'}]}}]})[0],'보이는 답변')

    def test_refusal_plain_text_fenced_json_and_incomplete(self):
        self.assertEqual(decode_text('```json\n{"reply":"네!","emotion":"thinking"}\n```'), ('네!', 'thinking'))
        self.assertEqual(decode_text('이 요청은 도와드리기 어려워요.')[1], 'cozy')
        for p, data in [('gemini',{'candidates':[]}), ('claude',{'stop_reason':'max_tokens'}),
                        ('vercel',{'choices':[{'finish_reason':'length'}]}), ('ollama',{'error':'no model'})]:
            with self.assertRaises(ValueError):parse_provider_response(p,data)

    def test_context_starts_with_user_even_after_trimming(self):
        payload=build_payload(DEFAULTS,[{'role':'assistant','content':'old'}, {'role':'user','content':'new'}])
        _,_,data=build_request('claude','fake',payload)
        self.assertEqual(data['messages'][0]['role'],'user')

import json
import unittest
from sse_toolcall_audit.core import audit


def sse(items,done=True):
    return ''.join('data: '+json.dumps(item,ensure_ascii=False)+'\n\n' for item in items)+('data: [DONE]\n\n' if done else '')


def chat(parts,name='read',finish='tool_calls'):
    items=[{'choices':[{'index':0,'delta':{'tool_calls':[{'index':0,'id':'call_1','type':'function','function':{'name':name,'arguments':parts[0]}}]},'finish_reason':None}]}]
    for part in parts[1:]:
        items.append({'choices':[{'index':0,'delta':{'tool_calls':[{'index':0,'function':{'arguments':part}}]},'finish_reason':None}]})
    items.append({'choices':[{'index':0,'delta':{},'finish_reason':finish}]})
    return sse(items)


class SseTests(unittest.TestCase):
    def test_split_json_and_unicode(self):
        report=audit(chat(['{"path":"','测试\u2028x','"}']))
        self.assertEqual(report['error_count'],0)
        self.assertNotIn('测试',json.dumps(report,ensure_ascii=False))

    def test_valid_chat_compares_semantically(self):
        final={'choices':[{'message':{'tool_calls':[{'function':{'name':'read','arguments':'{"b":2, "a":1}'}}]}}]}
        self.assertEqual(audit(chat(['{"a":1,','"b":2}']),final)['error_count'],0)
        final['choices'][0]['message']['tool_calls'][0]['function']['arguments']='{"a":2}'
        self.assertIn('stream_final_mismatch',audit(chat(['{"a":1}']),final)['finding_counts'])

    def test_invalid_arguments_and_truncation(self):
        report=audit(chat(['{"a":1'],finish='length'))
        self.assertIn('invalid_tool_arguments',report['finding_counts'])
        self.assertIn('incomplete_completion',report['finding_counts'])

    def test_no_tool_text_stream_is_valid(self):
        report=audit(sse([{'choices':[{'index':0,'delta':{'content':'hello'},'finish_reason':None}]},
                          {'choices':[{'index':0,'delta':{},'finish_reason':'stop'}]}]))
        self.assertEqual(report['error_count'],0)
        self.assertEqual(report['calls'],[])

    def test_missing_finish_and_terminal(self):
        capture=sse([{'choices':[{'index':0,'delta':{'content':'hello'},'finish_reason':None}]}],False)
        self.assertEqual(set(audit(capture)['finding_counts']),{'missing_terminal','missing_finish'})

    def test_blank_line_multiline_and_crlf(self):
        capture=': heartbeat\r\ndata: {"choices":\r\ndata: [{"index":0,"delta":{},"finish_reason":"stop"}]}\r\n\r\ndata: [DONE]\r\n\r\n'
        self.assertEqual(audit(capture)['error_count'],0)

    def test_eof_without_dispatch_boundary(self):
        self.assertIn('unterminated_event',audit('data: {"choices":[]}')['finding_counts'])
        self.assertIn('unterminated_event',audit('data: {"choices":[]}\n')['finding_counts'])

    def test_multiple_tools_in_single_delta(self):
        calls=[{'index':i,'id':f'c{i}','type':'function','function':{'name':'read','arguments':'{}'}} for i in range(2)]
        report=audit(sse([{'choices':[{'index':0,'delta':{'tool_calls':calls},'finish_reason':None}]},
                          {'choices':[{'index':0,'delta':{},'finish_reason':'tool_calls'}]}]))
        self.assertEqual(report['error_count'],0)
        self.assertEqual(len(report['calls']),2)

    def test_missing_function_name(self):
        self.assertIn('missing_tool_fields',audit(chat(['{}'],name=''))['finding_counts'])

    def responses(self,final='{"a":1}'):
        item={'type':'function_call','id':'fc1','call_id':'c1','name':'read','arguments':''}
        completed=dict(item,arguments=final)
        return [{'type':'response.output_item.added','output_index':0,'item':item},
                {'type':'response.function_call_arguments.delta','item_id':'fc1','delta':'{"a":'},
                {'type':'response.function_call_arguments.delta','item_id':'fc1','delta':'1}'},
                {'type':'response.function_call_arguments.done','item_id':'fc1','arguments':final},
                {'type':'response.output_item.done','output_index':0,'item':completed},
                {'type':'response.completed','response':{'output':[completed]}}]

    def test_responses_assembly_and_final(self):
        self.assertEqual(audit(sse(self.responses(),False))['error_count'],0)

    def test_responses_delta_final_corruption(self):
        report=audit(sse(self.responses('{"a":2}'),False))
        self.assertIn('delta_final_mismatch',report['finding_counts'])
        self.assertIn('stream_final_mismatch',report['finding_counts'])

    def test_server_error_never_looks_complete_success(self):
        self.assertIn('server_incomplete',audit(sse([{'type':'error','message':'private'}],False))['finding_counts'])

    def test_duplicate_keys_rejected(self):
        self.assertIn('invalid_tool_arguments',audit(chat(['{"a":1,"a":2}']))['finding_counts'])

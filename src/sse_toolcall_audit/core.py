"""Offline client-facing evidence; no server calls or argument repair."""
from collections import defaultdict
import hashlib
import json
from .common import Findings, integer, loads, text


def events(capture, findings):
    if not isinstance(capture, str):
        raise ValueError('Capture must be UTF-8 text.')
    if len(capture.encode('utf-8')) > 64 * 1024 * 1024:
        raise ValueError('Capture exceeds 64 MiB.')
    capture = capture.removeprefix('\ufeff').replace('\r\n','\n').replace('\r','\n')
    data, event_type, count = [], 'message', 0
    # split only CR/LF, never Unicode line separator characters in JSON strings.
    rows=capture.split('\n')
    if capture.endswith('\n'):
        rows.pop()  # The trailing split token is not a terminated blank line.
    for line in rows:
        if not line:
            if data:
                count += 1
                if count > 100_000:
                    raise ValueError('SSE event limit exceeded.')
                yield event_type, '\n'.join(data)
            data, event_type = [], 'message'
            continue
        if line.startswith(':'):
            continue
        field, separator, value = line.partition(':')
        if value.startswith(' '):
            value = value[1:]
        if field == 'data':
            data.append(value if separator else '')
        elif field == 'event':
            event_type = value
    if data:
        findings.add('unterminated_event', 'error', 'Capture ends before an SSE blank-line dispatch boundary.')


def arguments(value):
    if not isinstance(value, str):
        raise ValueError('Tool arguments must be a JSON string.')
    parsed = loads(value)
    if not isinstance(parsed, dict):
        raise ValueError('Tool arguments must decode to an object.')
    return parsed


def signature(name, args):
    return name, json.dumps(args, sort_keys=True, ensure_ascii=False, separators=(',',':'), allow_nan=False)


def final_signatures(expected):
    if not isinstance(expected, dict):
        raise ValueError('Comparison response must be an object.')
    result = []
    if 'choices' in expected:
        for choice in expected['choices']:
            for call in choice.get('message',{}).get('tool_calls',[]):
                function = call['function']
                result.append(signature(text(function['name'],'tool name'), arguments(function['arguments'])))
    elif 'output' in expected:
        for item in expected['output']:
            if item.get('type') == 'function_call':
                result.append(signature(text(item['name'],'tool name'), arguments(item['arguments'])))
    else:
        raise ValueError('Comparison must be a Chat Completions or Responses response.')
    return sorted(result)


def audit(capture, expected=None, api='auto'):
    if api not in {'auto','chat','responses'}:
        raise ValueError('Unsupported API dialect.')
    findings = Findings()
    calls = {}
    finished_choices = set()
    choices_seen = set()
    terminal, dialect, event_count = False, None, 0
    completed_response = None

    def call(key):
        return calls.setdefault(key, {'name':'','id':'','type':None,'argument_chunks':[],'done':False})

    def assembled(current):
        return ''.join(current['argument_chunks'])

    def done(key, final_value):
        current = call(key)
        if current['done']:
            findings.add('duplicate_tool_done','error','Tool arguments were finalized twice.', tool_key=str(key))
            return
        try:
            if arguments(assembled(current)) != arguments(final_value):
                findings.add('delta_final_mismatch','error','Assembled deltas differ from finalized arguments.',tool_key=str(key))
        except (ValueError, TypeError):
            findings.add('invalid_tool_arguments','error','Tool deltas or finalized arguments are not a strict JSON object.',tool_key=str(key))
        current['done'] = True

    for event_type, payload in events(capture, findings):
        event_count += 1
        if terminal:
            findings.add('event_after_terminal','error','Data event follows the terminal marker.',event=event_count)
            continue
        if payload == '[DONE]':
            if dialect == 'responses':
                findings.add('wrong_terminal','error','Responses completion requires response.completed, not only [DONE].')
            terminal = True
            continue
        try:
            item = loads(payload)
            if not isinstance(item, dict):
                raise ValueError('SSE JSON must be an object.')
        except (ValueError, TypeError):
            findings.add('invalid_event_json','error','SSE data is not a strict JSON object.',event=event_count)
            continue
        current_dialect = 'chat' if 'choices' in item else 'responses' if item.get('type','').startswith('response.') or item.get('type') == 'error' else None
        if current_dialect is None:
            findings.add('unknown_event','warning','Unrecognized API event shape.',event=event_count)
            continue
        if dialect and current_dialect != dialect:
            findings.add('mixed_dialects','error','Capture mixes API dialects.')
        dialect = current_dialect
        if api != 'auto' and api != dialect:
            findings.add('dialect_mismatch','error','Event does not match the requested dialect.')
        if dialect == 'chat':
            if not isinstance(item['choices'],list):
                raise ValueError('choices must be a list.')
            for choice in item['choices']:
                index = integer(choice.get('index'),'choice.index')
                choices_seen.add(index)
                delta = choice.get('delta',{})
                if not isinstance(delta,dict):
                    raise ValueError('delta must be an object.')
                if index in finished_choices and delta:
                    findings.add('delta_after_finish','error','Choice emitted data after its finish reason.',choice=index)
                for part in delta.get('tool_calls',[]):
                    tool_index = integer(part.get('index'),'tool.index')
                    current = call((index,tool_index))
                    if part.get('id'):
                        if current['id'] and current['id'] != part['id']:
                            findings.add('tool_id_conflict','error','Tool ID changed at the same choice/index.')
                        current['id'] = text(part['id'],'tool id')
                    if part.get('type') is not None:
                        current['type'] = part['type']
                    function = part.get('function',{})
                    for field in ('name','arguments'):
                        if function.get(field) is not None:
                            if not isinstance(function[field],str):
                                raise ValueError(f'function.{field} must be a string.')
                            if field == 'name':
                                if len(current['name']) + len(function[field]) > 1024:
                                    raise ValueError('Function name exceeds 1024 characters.')
                                current['name'] += function[field]
                            else:
                                current['argument_chunks'].append(function[field])
                reason = choice.get('finish_reason')
                if reason is not None:
                    if index in finished_choices:
                        findings.add('duplicate_finish','error','Choice finished more than once.',choice=index)
                    finished_choices.add(index)
                    if reason in {'length','content_filter'}:
                        findings.add('incomplete_completion','error','Completion ended before a normal stop.',choice=index,reason=reason)
                    for key,current in calls.items():
                        if key[0] == index:
                            current['done'] = True
                            if reason != 'tool_calls':
                                findings.add('tool_finish_reason','warning','Tool call exists without tool_calls finish reason.',choice=index)
        else:
            kind = item.get('type')
            if event_type != 'message' and event_type != kind:
                findings.add('event_type_mismatch','error','SSE event field differs from JSON type.',event=event_count)
            if kind == 'response.output_item.added' and item.get('item',{}).get('type') == 'function_call':
                entry = item['item']; key = text(entry.get('id'),'item id')
                if key in calls:
                    findings.add('duplicate_item','error','Function item was added twice.',tool_key=key)
                current = call(key)
                current.update(name=text(entry.get('name'),'tool name'), id=text(entry.get('call_id'),'call id'),type='function')
                # Initial arguments, if present, precede subsequent deltas.
                initial = entry.get('arguments','')
                if not isinstance(initial,str):
                    raise ValueError('Initial arguments must be a string.')
                current['argument_chunks'] = [initial]
            elif kind == 'response.function_call_arguments.delta':
                key = text(item.get('item_id'),'item id')
                if key not in calls:
                    findings.add('missing_item_start','error','Argument delta has no preceding function item.',tool_key=key)
                current = call(key)
                if current['done']:
                    findings.add('delta_after_tool_done','error','Argument delta follows finalization.',tool_key=key)
                value = item.get('delta')
                if not isinstance(value,str):
                    raise ValueError('Argument delta must be a string.')
                current['argument_chunks'].append(value)
            elif kind == 'response.function_call_arguments.done':
                key = text(item.get('item_id'),'item id')
                done(key,item.get('arguments'))
            elif kind == 'response.output_item.done' and item.get('item',{}).get('type') == 'function_call':
                entry = item['item']; key = text(entry.get('id'),'item id')
                current = call(key)
                if not current['done']:
                    findings.add('missing_arguments_done','error','Function item completed without arguments.done.',tool_key=key)
                try:
                    if arguments(assembled(current)) != arguments(entry.get('arguments')):
                        findings.add('item_final_mismatch','error','Output item arguments differ from assembled deltas.',tool_key=key)
                except (ValueError,TypeError):
                    findings.add('invalid_item_arguments','error','Completed output item arguments are invalid.',tool_key=key)
            elif kind == 'response.completed':
                terminal = True
                completed_response = item.get('response')
                if not isinstance(completed_response,dict):
                    findings.add('missing_final_response','error','response.completed lacks a response object.')
            elif kind in {'response.incomplete','response.failed','error'}:
                terminal = True
                findings.add('server_incomplete','error','Server emitted a failure/incomplete event; diagnostic does not repair it.')
    if not terminal:
        findings.add('missing_terminal','error','No terminal marker was observed.')
    if not event_count:
        findings.add('empty_capture','error','No SSE data events were observed.')
    if dialect is None:
        findings.add('no_api_events','error','No supported API events were observed.')
    if dialect == 'chat':
        for index in sorted(choices_seen - finished_choices):
            findings.add('missing_finish','error','Choice has no finish reason.',choice=index)
    summaries, signatures = [], []
    used_ids = set()
    for key,current in calls.items():
        if not current['name'] or not current['id'] or current['type'] != 'function':
            findings.add('missing_tool_fields','error','Assembled function call lacks name, ID, or function type.',tool_key=str(key))
        if current['id'] in used_ids and current['id']:
            findings.add('duplicate_call_id','error','Two function calls share the same call ID.')
        used_ids.add(current['id'])
        if not current['done']:
            findings.add('unfinished_tool','error','Tool call was not finalized.',tool_key=str(key))
        valid = False
        try:
            args = arguments(assembled(current))
            signatures.append(signature(current['name'],args)); valid = True
        except (ValueError,TypeError):
            findings.add('invalid_tool_arguments','error','Assembled tool arguments are not a strict JSON object.',tool_key=str(key))
        raw = assembled(current).encode('utf-8')
        summaries.append(dict(key=str(key),name=current['name'],id=current['id'],finished=current['done'],valid_json=valid,
                              argument_bytes=len(raw),arguments_sha256=hashlib.sha256(raw).hexdigest()))
    for candidate,label in [(completed_response,'completed_response'),(expected,'comparison_response')]:
        if candidate is not None:
            try:
                if final_signatures(candidate) != sorted(signatures):
                    findings.add('stream_final_mismatch','error','Tool names/semantic arguments differ from the final response.',source=label)
            except (ValueError,TypeError,KeyError):
                findings.add('invalid_comparison','error','Final response cannot be compared safely.',source=label)
    return dict(tool='sse-toolcall-audit',schema_version=1,api=dialect,events=event_count,terminal=terminal,
                calls=summaries, argument_values_in_report=False, **findings.report())

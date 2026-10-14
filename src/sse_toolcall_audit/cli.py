import argparse
from pathlib import Path
import sys
from .common import load, emit, code
from .core import audit


def main(argv=None):
    parser=argparse.ArgumentParser(description='Offline Chat Completions/Responses SSE evidence auditor.')
    parser.add_argument('capture')
    parser.add_argument('--compare',help='Saved non-streaming response JSON.')
    parser.add_argument('--api',choices=['auto','chat','responses'],default='auto')
    parser.add_argument('--strict',action='store_true')
    parser.add_argument('--output')
    args=parser.parse_args(argv)
    try:
        with Path(args.capture).open('rb') as stream:
            raw=stream.read(64*1024*1024+1)
        if len(raw)>64*1024*1024: raise ValueError('Capture exceeds 64 MiB.')
        report=audit(raw.decode('utf-8-sig'), load(args.compare) if args.compare else None,args.api)
        emit(report,args.output)
        return code(report,args.strict)
    except (OSError,ValueError,TypeError,KeyError,AttributeError) as exc:
        print(f'Input/report error: {exc}',file=sys.stderr)
        return 2

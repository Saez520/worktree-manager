"""Stable human and JSON contract-v1 output."""
from __future__ import annotations
import json,sys
from .models import OperationResult

def emit(result: OperationResult,as_json: bool)->None:
    if as_json: print(json.dumps(result.json_document(),ensure_ascii=False,separators=(',',':')))
    else:
        print(f'operation: {result.operation}\nresult: {result.result.value}')
        for key,value in result.data.items(): print(f'{key}: {value}')
        if result.error: print(result.error.message,file=sys.stderr)

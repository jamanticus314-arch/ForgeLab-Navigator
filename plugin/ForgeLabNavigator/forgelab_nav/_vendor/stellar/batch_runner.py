"""Ordered, exact-identity batch runner (Gemini draft, corrected locally)."""
from __future__ import annotations
import json
import itertools
import multiprocessing as mp
import os
from pathlib import Path
import time
from collections import deque

_generator = None
_init_error = None

def exact_address(value):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise TypeError('Address must be an integer or decimal string')
    if isinstance(value,str) and (not value.isascii() or not value.isdecimal()):
        raise ValueError('Address string must contain ASCII decimal digits only')
    value = int(value)
    if not 0 <= value < 1 << 64:
        raise ValueError('Address is outside uint64')
    return value

def available_workers():
    return (getattr(os, 'process_cpu_count', os.cpu_count)() or 1)

def _init_worker():
    global _generator, _init_error
    _generator = None
    _init_error = None
    try:
        from .api import StellarGenerator
        _generator = StellarGenerator()
    except Exception as exc:
        _init_error = repr(exc)

def _process_item(task):
    index,address,companions=task
    row={'index':index,'address':str(address)}
    try:address=exact_address(address)
    except (TypeError,ValueError) as exc:
        return dict(row,status='invalid_input',error=str(exc))
    if _init_error:
        return dict(row,status='error',error='Worker initialization: '+_init_error)
    try:
        result=_generator.predict(address,companions=companions)
        if not isinstance(result,dict):raise TypeError('Generator returned a non-dictionary')
        row.update(result)
        row.update(index=index,address=str(address))
        return row
    except Exception as exc:
        return dict(row,status='error',error=repr(exc))

def _process_block(tasks):
    return [_process_item(task) for task in tasks]


def _blocks(tasks,limit):
    """Keep adjacent addresses in the same boxel on one worker, bounded in size."""
    block=[];previous=None
    for task in tasks:
        try:
            address=exact_address(task[1])
            key=address&((1<<(44-3*(address&7)))-1)
        except (TypeError,ValueError):key=('invalid',task[0])
        if block and (key!=previous or len(block)>=limit):
            yield block;block=[]
        block.append(task);previous=key
    if block:yield block


def _parallel_rows(pool,tasks,workers,chunksize):
    """At most two pending work blocks per worker, including ordered results."""
    blocks=iter(_blocks(tasks,chunksize));pending=deque();exhausted=False
    while pending or not exhausted:
        while not exhausted and len(pending)<2*workers:
            try:block=next(blocks)
            except StopIteration:exhausted=True;break
            pending.append(pool.apply_async(_process_block,(block,)))
        if pending:
            yield from pending.popleft().get()


def run_batch(addresses, *, workers=None, companions=False, output_path=None, chunksize=256, row_sink=None):
    """Return summary and optional rows; file mode streams ordered JSONL.

    Timing includes worker startup, asset load and output serialization. Supply
    output_path or row_sink for bounded-memory output; otherwise rows are returned.
    A failed process or interrupted run retains the explicitly named partial file.
    """
    started=time.perf_counter()
    if workers is not None and (isinstance(workers,bool) or not isinstance(workers,int) or workers<1):
        raise ValueError('workers must be a positive integer or None for all available CPUs')
    if isinstance(chunksize,bool) or not isinstance(chunksize,int) or chunksize<1:
        raise ValueError('chunksize must be a positive integer')
    if row_sink is not None and (not callable(row_sink) or output_path is not None):
        raise ValueError('row_sink must be callable and cannot accompany output_path')
    requested=available_workers() if workers is None else workers
    # Prime at most one address per requested worker. JSONL/text callers can
    # supply hundreds of millions of identities without loading them all.
    source=iter(addresses)
    head=list(itertools.islice(source,requested))
    used=len(head)
    output=Path(output_path) if output_path is not None else None
    partial=summary_path=None
    handle=None
    if output is not None:
        summary_path=Path(str(output)+'.summary.json')
        partial=Path(str(output)+'.partial')
        for path in (output,summary_path,partial):
            if path.exists():raise FileExistsError(path)
        output.parent.mkdir(parents=True,exist_ok=True)
        handle=partial.open('x',encoding='utf-8',newline='\n')
    rows=[] if output is None and row_sink is None else None
    statuses={};received=records=procedural=0
    tasks=((i,address,companions) for i,address in
           enumerate(itertools.chain(head,source)))
    pool=None
    try:
        if used>1:
            # Pool has no ProcessPoolExecutor's Windows 61-worker restriction.
            pool=mp.get_context('spawn').Pool(used,initializer=_init_worker)
            iterator=_parallel_rows(pool,tasks,used,chunksize)
        elif used==1:
            _init_worker();iterator=map(_process_item,tasks)
        else:iterator=iter(())
        for row in iterator:
            received+=1
            status=row.get('status','unknown');statuses[status]=statuses.get(status,0)+1
            records+=int(row.get('record') is not None)
            procedural+=int(status in ('procedural','procedural_with_override'))
            if handle is not None:handle.write(json.dumps(row,separators=(',',':'))+'\n')
            elif row_sink is not None:row_sink(row)
            else:rows.append(row)
        if pool is not None:pool.close();pool.join();pool=None
        if handle is not None:
            handle.flush();os.fsync(handle.fileno());handle.close();handle=None
            if output.exists():raise FileExistsError(output)
            os.rename(partial,output)
    finally:
        if pool is not None:pool.terminate();pool.join()
        if handle is not None:handle.flush();handle.close()
    elapsed=time.perf_counter()-started
    summary={'input_count':received,'output_count':received,'status_counts':statuses,
        'records_present':records,'procedural_records':procedural,'requested_workers':requested,
        'used_workers':used,'available_cpus':available_workers(),'elapsed_seconds':elapsed,
        'requests_per_second':received/elapsed if elapsed else 0,
        'records_per_second':records/elapsed if elapsed else 0,
        'procedural_systems_per_second':procedural/elapsed if elapsed else 0,
        'includes_startup_and_output':True,'companions_requested':companions,
        'max_addresses_per_work_block':chunksize,'max_pending_work_blocks':2*used if used>1 else 0,
        'preserves_adjacent_boxel_locality':True,
        'output_path':str(output.resolve()) if output is not None else None}
    if summary_path is not None:
        with summary_path.open('x',encoding='utf-8') as f:json.dump(summary,f,indent=2);f.write('\n')
    return {'summary':summary,'rows':rows}

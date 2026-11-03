"""Prepare 100k unique fictional Chinese texts with real frozen Tencent1024 embeddings."""
import argparse
import asyncio
import hashlib
import json
import math
import random
import sqlite3
import sys
import time
from array import array
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'scripts'))
from b0_accounts import credential

ROOT = REPO / '.local/phase2/b0/completion-20261028/capacity'
COUNT = 100000
SEED = 2026102801
MODEL = 'kinfra-text-embedding-0.6b'
BATCH = 32
BUDGET = 4000


def corpus():
    # Only retain source length distribution; no real conversation or gold text is exported.
    path = REPO / '.local/phase2/b0/data-v2/dulemon_gold-dev.jsonl'
    lengths = [len(g['candidate']) for s in path.read_text().splitlines()
        for g in json.loads(s)['metadata']['gold_memory_points']]
    rng = random.Random(SEED)
    topics = ['阅读', '运动', '绘画', '音乐', '编程', '旅行', '摄影', '烹饪']
    places = ['书房', '客厅', '公园', '阳台', '图书馆', '工作室']
    rows = []
    for i in range(COUNT):
        length = max(32, min(384, rng.choice(lengths)))
        lead = f'虚构压测记录{i:06d}：'
        text = lead + f'测试人物偏好{rng.choice(topics)}，通常在{rng.choice(places)}活动。'
        text += '此内容仅用于隔离性能评测，不涉及真实个人。' * 20
        rows.append((i, text[:length]))
    assert len({text for _, text in rows}) == COUNT
    return rows, {'gold_length_source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'length_min': min(lengths), 'length_max': max(lengths),
        'generation': 'unique deterministic entirely fictional templates sampled to frozen gold memory length distribution, clipped32..384 chars; no real source text copied; synthetic performance workload, not semantic quality',
        'seed': SEED}


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--account', choices=('tokenhub-primary', 'tokenhub-secondary'), default='tokenhub-primary')
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    texts, provenance = corpus()
    db = sqlite3.connect(ROOT / 'vectors-private.sqlite')
    db.execute('CREATE TABLE IF NOT EXISTS vectors (id INTEGER PRIMARY KEY, text TEXT NOT NULL, vector BLOB NOT NULL, response_sha256 TEXT NOT NULL)')
    done = {r[0] for r in db.execute('SELECT id FROM vectors')}
    usage = ROOT / 'usage-private.jsonl'
    prior = [json.loads(s) for s in usage.read_text().splitlines()] if usage.exists() else []
    attempts = len(prior)
    _, base, token = credential(args.account)
    lock = asyncio.Lock()
    gate = asyncio.Semaphore(4)
    stopped = False
    started = time.time()
    plan = {'texts': COUNT, 'batch_size': BATCH, 'planned_batches': math.ceil(COUNT / BATCH),
        'attempt_cap_with_reserve': BUDGET, 'reserve_attempts': BUDGET - math.ceil(COUNT / BATCH),
        'pilot_tokens_per_text': 886 / 32, 'estimated_tokens_at_pilot_length': COUNT * 886 / 32,
        'model': MODEL, 'dimensions': 1024, **provenance,
        'limitation': 'budget is operational headroom, not confirmed balance; generation lengths differ from pilot, actual usage recorded; no model auto-switch'}
    (ROOT / 'vector-plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'plan': plan, 'already_completed': len(done)}, ensure_ascii=False), flush=True)
    async with httpx.AsyncClient(trust_env=False, timeout=90) as client:
        async def one(batch):
            nonlocal attempts, stopped
            if all(i in done for i, _ in batch):
                return
            assert not any(i in done for i, _ in batch), 'partial batch requires explicit repair'
            async with gate:
                body = {'model': MODEL, 'input': [s for _, s in batch]}
                for retry in range(4):
                    async with lock:
                        if stopped:
                            return
                        if attempts >= BUDGET:
                            stopped = True
                            return
                        attempts += 1
                        call = attempts
                    start = time.monotonic()
                    request = ROOT / f'calls/{call:05d}-request-private.json'
                    request.parent.mkdir(exist_ok=True, mode=0o700)
                    request.write_text(json.dumps(body, ensure_ascii=False) + '\n'); request.chmod(0o600)
                    response = None
                    data = {}
                    try:
                        response = await client.post(base + '/embeddings', headers={'Authorization': 'Bearer ' + token}, json=body)
                        data = response.json()
                    except (httpx.TransportError, ValueError):
                        pass
                    raw = json.dumps(data, separators=(',', ':'))
                    path = ROOT / f'calls/{call:05d}-response-private.json'
                    path.write_text(raw + '\n'); path.chmod(0o600)
                    record = {'account': args.account, 'call': call, 'first_id': batch[0][0], 'count': len(batch),
                        'http': response.status_code if response is not None else None,
                        'seconds': time.monotonic() - start, 'usage': data.get('usage'), 'model': data.get('model'),
                        'request_sha256': hashlib.sha256(request.read_bytes()).hexdigest(),
                        'response_sha256': hashlib.sha256(raw.encode()).hexdigest()}
                    with usage.open('a') as f:
                        f.write(json.dumps(record) + '\n')
                    code = record['http']
                    if code == 200:
                        vectors = data.get('data', [])
                        if data.get('model') != MODEL or len(vectors) != len(batch):
                            stopped = True
                            raise RuntimeError('FROZEN_VECTOR_BATCH_MODEL_OR_COUNT_MISMATCH')
                        vectors = sorted(vectors, key=lambda v: v['index'])
                        for (index, text), item in zip(batch, vectors, strict=True):
                            vector = item['embedding']
                            if len(vector) != 1024 or not all(math.isfinite(x) for x in vector) or not any(vector):
                                stopped = True
                                raise RuntimeError('FROZEN_VECTOR_INVALID_NATIVE_SHAPE')
                            db.execute('INSERT INTO vectors VALUES (?,?,?,?)',
                                (index, text, array('f', vector).tobytes(), record['response_sha256']))
                        db.commit()
                        done.update(i for i, _ in batch)
                        if len(done) % 2048 == 0 or len(done) == COUNT:
                            print(json.dumps({'completed': len(done), 'attempts': attempts, 'elapsed': time.time() - started}), flush=True)
                        return
                    if code == 402 or code in (400, 401, 403, 404):
                        stopped = True
                        print(json.dumps({'paused_http': code, 'completed': len(done), 'call': call}), flush=True)
                        return
                    await asyncio.sleep(min(2 ** (retry + 1), 20))
                stopped = True
        await asyncio.gather(*(one(texts[i:i+BATCH]) for i in range(0, COUNT, BATCH)))
    count = db.execute('SELECT count(*) FROM vectors').fetchone()[0]
    db.close()
    (ROOT / 'vectors-private.sqlite').chmod(0o600)
    usage.chmod(0o600)
    status = {'status': 'complete' if count == COUNT else 'paused', 'vectors': count, 'model': MODEL,
        'dimensions': 1024, 'account': args.account, 'attempts': attempts, 'model_switched': False, 'source_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (ROOT / 'status.json').write_text(json.dumps(status, indent=2) + '\n')
    print(json.dumps(status), flush=True)


if __name__ == '__main__':
    asyncio.run(main())

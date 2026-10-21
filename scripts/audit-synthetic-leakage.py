"""Audit actual archived annotation requests and construction shortcuts, without model calls."""
import argparse
import json
from collections import Counter
from pathlib import Path
from agent_memory.evals.datasets import file_hash
from agent_memory.evals.labeling import load_labels

p = argparse.ArgumentParser()
p.add_argument('--timeline', type=Path, required=True)
p.add_argument('--campaign', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
items = [json.loads(s) for s in (a.timeline/'items.jsonl').read_text().splitlines()]
left = load_labels(a.campaign/'timeline-v2-deepseek/labels.jsonl')
right = load_labels(a.campaign/'timeline-v2-hy4/labels.jsonl')
assert {r['item_id'] for r in items} == left.keys() == right.keys()
forbidden = {'answer', 'label', 'gold', 'expected', 'negative_design', 'personas', 'questions',
             'user_said_persona', 'user_no_said_persona', 'reference_label'}

def paths(value, path=''):
    found = []
    if isinstance(value, dict):
        for k,v in value.items():
            if k in forbidden: found.append(path+'/'+k)
            found += paths(v,path+'/'+k)
    elif isinstance(value,list):
        for i,v in enumerate(value): found += paths(v,path+'/'+str(i))
    return found

requests = []
covered = Counter()
for f in sorted((a.campaign/'timeline-v2-cache').glob('*.json')):
    raw = json.loads(f.read_text())
    body = raw['request']
    payload = json.loads(body['messages'][1]['content'])
    row = {'file': f.name, 'sha256': file_hash(f), 'model': body['model'],
           'forbidden_answer_field_paths': paths(payload),
           'item_count':len(payload['items']), 'temperature':body['temperature'],
           'thinking':body.get('thinking'), 'top_level_keys': sorted(payload)}
    covered[body['model']] += len(payload['items'])
    row['item_keys'] = sorted({k for r in payload['items'] for k in r})
    row['source_document_keys'] = sorted({k for docs in payload['sources'].values() for d in docs for k in d})
    row['raw_ids_exposed'] = any('customer-timeline' in r['item_id'] for r in payload['items'])
    requests.append(row)
# This diagnostic predicts labels using NO candidate semantics and NO model calls.
source_only = {r['item_id']: 'keep' if len(r['source']) == 3 else 'discard' for r in items}
order_only = {r['item_id']: 'keep' if i < 1500 else 'discard' for i,r in enumerate(items)}
labels = [left[r['item_id']].label for r in items]
transitions = sum(a != b for a,b in zip(labels,labels[1:]))
pure_batches = []
for model_dir in ['timeline-v2-deepseek','timeline-v2-hy4']:
    for f in sorted((a.campaign/model_dir).glob('input-*.jsonl')):
        rows=[json.loads(s) for s in f.read_text().splitlines()]
        for start in range(0,len(rows),50):
            pure_batches.append(len({left[r['item_id']].label for r in rows[start:start+50]})==1)
result = {
 'status': '流程验证，不作质量证据',
 'items':len(items), 'models_agree':sum(left[k].label==right[k].label for k in left),
 'label_counts':dict(Counter(labels)), 'actual_request_files':len(requests),
 'request_item_coverage_by_model':dict(covered),
 'explicit_answer_fields_in_user_payload':sum(len(r['forbidden_answer_field_paths']) for r in requests),
 'raw_identifiers_exposed_requests':sum(r['raw_ids_exposed'] for r in requests),
 'candidate_blind_source_length_predictor_matches':sum(source_only[k]==left[k].label for k in left),
 'content_blind_original_order_predictor_matches':sum(order_only[k]==left[k].label for k in left),
 'source_document_count_histogram':dict(Counter(len(r['source']) for r in items)),
 'label_transitions_in_original_order':transitions,
 'label_pure_batches':sum(pure_batches), 'batches':len(pure_batches),
 'negative_source_text_variants':len({json.dumps(r['source'],sort_keys=True,ensure_ascii=False)
                                    for r in items if left[r['item_id']].label=='discard'}),
 'candidate_form_count':len({r['candidate'] for r in items}),
 'construction': 'scripts/prepare-timeline-review.py directly creates five supported facts for each positive user and an unsupported tea preference for every goodbye-only negative user',
 'conclusions': [
  'Actual user payloads contain source documents/candidates and reversible compact IDs, not constructor answer labels, questions or timeline metadata.',
  'Source length alone and original position alone perfectly predict both model outputs; batches are class-pure. Explicit field leakage was not found, but structural/order shortcuts exist.',
  'Generator directly determines support labels, positive wording is explicit and negative conversations are identical. This task is too simple to establish real annotation quality.',
  'Offline diagnostics demonstrate confounding, not proof that either model actually used a particular shortcut. No randomized counterfactual model experiment was run.',
 ],
 'proposed_next_campaign_not_executed': [
  'Version a new corpus with hard attribution, transient statements, uncertain inference, corrections, quoted third-person facts, paraphrases, balanced within each length/session-count stratum.',
  'Randomize candidates and opaque identifiers per model; hide constructor metadata and keep truth in a separate private file.',
  'Compare original/shuffled/masked-metadata and semantic counterfactual samples; add independent owner audit before making quality claims.',
  'Require owner approval for any annotator replacement and keep entire new batch separate; do not alter current frozen split or labels.',
 ],
 'input_sha256':file_hash(a.timeline/'items.jsonl'),
 'generator_sha256':file_hash(Path('scripts/prepare-timeline-review.py')),
 'annotation_prompt_sha256':json.loads((a.campaign/'timeline-v2-deepseek/manifest.json').read_text())['prompt_sha256'],
 'requests':requests,
 'calls_in_this_audit':0, 'phase1_accepted':False,
}
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in result.items() if k not in ('requests','conclusions','proposed_next_campaign_not_executed')},ensure_ascii=False))

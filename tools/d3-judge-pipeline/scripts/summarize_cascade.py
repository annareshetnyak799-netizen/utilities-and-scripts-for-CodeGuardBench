"""Rebuild tables from completed result files; never fabricate unavailable metrics."""
import csv,json,collections
from pathlib import Path
from judge.io import read_records,dump
from codeguard_judge.policy import REGISTRY
from codeguard_judge.evaluation import metrics
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/cascade_2026-11-05';EXP=OUT/'experiments'
refs={r['record_id']:r for r in read_records(EXP/'pilot_references.jsonl')};summaries=[];errors=[];detail=[]
for name in ['rules','single','static_single','reasoning_single','critic_cascade','specialists','semantic_cascade']:
 path=EXP/name
 if not (path/'metrics.json').exists():continue
 m=json.loads((path/'metrics.json').read_text());rs=read_records(path/'results.jsonl')
 raw_pairs=[]
 for r in rs:
  cls=next((j for j in r['judges'] if j.get('role')=='classifier'),None)
  answer=cls.get('response',{}) if cls and not cls['errors'] else {}
  raw_pairs.append((dict(r,predicted_class=answer.get('predicted_class'),predicted_primary_risk=answer.get('risk'),severity=answer.get('severity')),refs[r['record_id']]))
  for j in r['judges']:
   for e in j['errors']:errors.append({'run':name,'record_id':r['record_id'],'model':j.get('model_id'),'error':e})
  detail.append({'run':name,'record_id':r['record_id'],'category':refs[r['record_id']]['category'],'source':refs[r['record_id']]['source'],'reference_class':refs[r['record_id']]['class'],'reference_risk':refs[r['record_id']]['risk'],'proposal_class':answer.get('predicted_class'),'final_class':r['predicted_class'],'final_risk':r['predicted_primary_risk'],'review_reasons':';'.join(r['review_reasons'])})
 raw=metrics(raw_pairs)
 summaries.append({'architecture':name,'n':m['n'],'annotation_agreement':m['annotation_agreement'],'coverage':m['prediction_coverage'],'raw_proposal_agreement':raw['annotation_agreement'] if name!='rules' else m['annotation_agreement'],'raw_proposal_coverage':raw['prediction_coverage'] if name!='rules' else m['prediction_coverage'],'macro_f1':m['class_macro_f1'],'false_allow_rate':m['binary_false_allow_rate'],'calls':m['calls'],'estimated_rub':m['estimated_cost_rub'],'latency_s':m['latency_s'],'human_gold_accuracy':'NOT_AVAILABLE'})
for file,rows in [('TEAM_COMPARISON.csv',summaries),('all_disagreements_and_decisions.csv',detail),('validation_errors.csv',errors)]:
 with (OUT/file).open('w',newline='') as f:
  if rows:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
inv=json.load(open(OUT/'discovery_v2/inventory.json'));fixtures=collections.Counter(r['diagnostic_family'] for r in read_records(ROOT/'tests/fixtures/all_taxonomy.jsonl'));pilot=collections.Counter(r['risk'] for r in refs.values());probe={r['record_id']:r for r in read_records(OUT/'taxonomy_probe/run/results.jsonl')} if (OUT/'taxonomy_probe/run/results.jsonl').exists() else {}
with (OUT/'TAXONOMY_COVERAGE.csv').open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=['risk','registry','independent_diagnostic_fixtures','peer_v0_test_rows','blind_pilot_rows','real_authored_probe_model_calls','human_gold','semantic_validation']);w.writeheader()
 for c in REGISTRY['cards']:
  key=c['id'];p=probe.get('fixture-'+key[4:]+'-0',{})
  w.writerow({'risk':key,'registry':1,'independent_diagnostic_fixtures':fixtures[key],'peer_v0_test_rows':inv['taxonomy_counts'][key],'blind_pilot_rows':pilot[key],'real_authored_probe_model_calls':len(p.get('judges',[])),'human_gold':0,'semantic_validation':'NOT_VALIDATED'})
lines=['# Сравнение архитектур, слепой diagnostic pilot\n','Одинаковые 32 ID из 16 peer risk codes, command-only. Selection фиксирован до запросов; по две строки на risk с разными метками при наличии. Это стратифицированный стресс-пилот, не оценка генеральной совокупности. Данные ранее обсуждались в проекте: historical diagnostic, не pristine holdout. Human gold=0.\n','| Архитектура | Agreement, все32 | Coverage | Agreement raw proposal | Calls | RUB estimate |\n|---|---:|---:|---:|---:|---:|']
for r in summaries:lines.append(f"| {r['architecture']} | {r['annotation_agreement']:.1%} | {r['coverage']:.1%} | {r['raw_proposal_agreement']:.1%} | {r['calls']} | {r['estimated_rub']:.3f} |")
lines+=['\nRaw proposal — schema-valid ответ первого классификатора до фильтра контекста/критика; final agreement — после этих проверок. Abstain остаётся в знаменателе. Рост отказов не доказывает рост качества. False-allow здесь означает расхождение с существующей меткой, не подтверждённый вред.','\nSingle/static/critic/specialists используют Qwen3-32B первым классификатором; reasoning_single — gpt-oss-120b. semantic_cascade дополнительно вызывает semantic stage Qwen, затем classifier Qwen, затем critic gpt-oss. Specialists — предсказание generalist определяет CAT карточки независимому gpt-oss. Ошибка router может перенестись на специалиста; это измеряемое ограничение.','\nВсе calls — реальные; модель может не вызываться из-за синтаксиса/неизвестного executable. Частоты schema failures, provider errors, category breakdown, confusion и disagreements лежат в каталогах каждого run. Reasoning tokens взяты из usage; hidden chain of thought не сохранялся.','\nSampling seed и temperature не фиксировались: использованы defaults провайдера. Повторные classifier calls в архитектурах не идентичны. Поэтому это пилот работы маршрутов, не чистая причинная оценка выигрыша каждого этапа. Для чистой static ablation используйте replay одного сохранённого ответа.','\nНи одного human gold примера нет, лидер по качеству не выбран. Не использовать эту таблицу для автоматического приёма новых gold-меток.']
legacy=EXP/'legacy_v1_reasoning/annotation_agreement.json'
if legacy.exists():
 l=json.loads(legacy.read_text());lines.append(f"\nLegacy v1 с gpt-oss-120b действительно прогнан на тех же32 ID: raw annotation agreement {l['annotation_agreement']:.1%}, raw coverage {l['prediction_coverage']:.1%}. Его CAT-2-only policy/schema и правила gating отличаются; он вынесен отдельно (`legacy_v1_reasoning/annotation_agreement.json`), не скрыто объединён в matched-policy comparison.")
lines.append('\nLegacy v1/Qwen сохранён как PARTIAL_NOT_SCORED после повторных provider timeouts; INTERRUPTED.json фиксирует число обработанных строк. Static replay использует те же ответы single, без новых вызовов: experiments/static_replay/replay_receipt.json. Один ID изменён правилом. Usage replay не прибавляется к затратам.')
(OUT/'CASCADE_COMPARISON.md').write_text('\n'.join(lines)+'\n')
counts=collections.Counter(e['error'] for e in errors)
lines=['# Разбор отказов и разногласий\n','Все counts ниже получены из сохранённых ответов, не из впечатлений. Ошибка метки коллег или judge не устанавливается автоматически.\n','| Ошибка валидации | Calls |\n|---|---:|']+[f'| {k} | {v} |' for k,v in counts.most_common()]
lines+=['\nSchema failures: модели иногда возвращают недопустимый тип/enum или policy refs без соответствующего primary risk. Nonliteral evidence: пересказ вместо точной подстроки. Missing_review_flag: модель указывает missing_context, но не ставит review. Все такие ответы не получают финальную action label.','\nUnknown executable — консервативный gate, а не доказательство опасности. KNOWN список неполон; это уменьшает coverage даже для известных человеку утилит. Bashlex unsupported также не равен unsafe.','\nНаблюдаемые расхождения следует рассматривать в порядке: (1) ошибка формата/модели, (2) видимость контекста, (3) конфликт правил, (4) curated counterexample risk, (5) возможная ошибка reference. Без человека не сводить их к одной accuracy.','\nПолный построчный файл: all_disagreements_and_decisions.csv. Для слепого человека: human_review/blind_review.jsonl; reference_key не показывать до первого решения.','\nНачать калибровку с 52 карточек. Не менять prompts по текущему holdout после просмотра этих ответов; следующую версию проверять на новом заранее замороженном наборе.']
(OUT/'ERROR_ANALYSIS.md').write_text('\n'.join(lines)+'\n')
print({'completed_architectures':len(summaries),'validation_error_events':len(errors)})

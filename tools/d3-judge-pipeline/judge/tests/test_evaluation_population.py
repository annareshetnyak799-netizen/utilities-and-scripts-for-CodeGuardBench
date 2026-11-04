"""A dropped or duplicated answer must not silently change experiment weights."""
import json
import pytest
from judge.evaluate import score


def result(key, label='allow'):
    response = {'predicted_class': label, 'risk': 'CAT-2.3'}
    return {'record_id': key, 'judges': [{'response': response, 'errors': [],
            'raw': json.dumps(response)}], 'status': 'needs_review'}


def references():
    return [{'record_id': key, 'class': 'allow', 'risk': 'CAT-2.3',
             'human_reviewed': False} for key in ('a', 'b')]


@pytest.mark.parametrize('rows, error', [
    ([result('a'), result('a')], 'duplicate_result_id'),
    ([result('a')], 'missing_result_id'),
    ([result('a'), result('b'), result('c')], 'unexpected_result_id'),
    ([result('a'), result('')], 'invalid_result_id'),
])
def test_reject_changed_population(rows, error):
    with pytest.raises(ValueError, match=error):
        score(rows, references(), diagnostic=True)


@pytest.mark.parametrize('expected, error', [
    (['a', 'a'], 'duplicate_expected_id'),
    (['c'], 'expected_id_missing_reference'),
    ([], 'empty_evaluation_population'),
    ('a', 'invalid_expected_ids'),
])
def test_reject_invalid_population_declaration(expected, error):
    with pytest.raises(ValueError, match=error):
        score([result('a')], references(), diagnostic=True, expected_ids=expected)


def test_explicit_subset_and_failed_answer_keep_denominator():
    single = score([result('b')], references(), diagnostic=True, expected_ids=['b'])
    assert single['n'] == single['expected_n'] == 1
    assert single['reference_n'] == 2 and single['expected_ids'] == ['b']
    failed = result('b')
    failed['judges'] = [{'response': None, 'errors': ['timeout']}]
    full = score([failed, result('a')], references(), diagnostic=True)
    assert full['n'] == 2 and full['accuracy'] == full['class_coverage'] == 0.5
    assert full['population_complete'] is True
    with pytest.raises(ValueError, match='independent_human_gold_required'):
        score([result('b')], references(), expected_ids=['b'])


def test_duplicate_references_rejected_even_with_subset():
    with pytest.raises(ValueError, match='duplicate_reference_id'):
        score([result('a')], references() + [references()[0]], diagnostic=True, expected_ids=['a'])

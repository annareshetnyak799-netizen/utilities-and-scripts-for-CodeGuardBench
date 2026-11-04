import pytest
from judge.cuda_adapter import check_config, memory_budget, validate_device_map

GIB = 1024**3

def test_budget_uses_each_devices_free_memory_and_reserves_inference_space():
    assert memory_budget([15*GIB, 9*GIB], 2) == {0: 13*GIB, 1: 7*GIB}
    with pytest.raises(ValueError):
        memory_budget([15*GIB, GIB], 2)
    with pytest.raises(ValueError):
        memory_budget([])

def test_no_silent_cpu_or_disk_offload():
    validate_device_map({'embed': 0, 'layer': 'cuda:1'})
    for value in ['cpu', 'disk', 'meta', -1]:
        with pytest.raises(ValueError):
            validate_device_map({'embed': 0, 'layer': value})

def test_pilot_rejects_mutable_revision_and_implicit_runtime_changes():
    config = dict(revision='a'*40, quantization='nf4', device_map='auto')
    check_config(config)
    for changes in [dict(revision='main'), dict(quantization=None),
                    dict(enable_thinking=True), dict(do_sample=True), dict(device_map=None)]:
        with pytest.raises(ValueError):
            check_config(dict(config, **changes))

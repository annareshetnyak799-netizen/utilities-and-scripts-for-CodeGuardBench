"""Explicit CUDA/NF4 inference. Does not execute any input shell text."""
import hashlib
import importlib.metadata
import re


def memory_budget(free_bytes, reserve_gib=2):
    reserve = int(reserve_gib * 1024**3)
    if reserve < 1024**3:
        raise ValueError('reserve_at_least_one_gib_for_inference')
    if not free_bytes or any(value <= reserve for value in free_bytes):
        raise ValueError('insufficient_free_gpu_memory')
    return {index: int(value - reserve) for index, value in enumerate(free_bytes)}


def check_config(config):
    if not re.fullmatch(r'[0-9a-f]{40}', config.get('revision', '')):
        raise ValueError('cuda_requires_immutable_hf_revision')
    if config.get('quantization') != 'nf4':
        raise ValueError('cuda_pilot_requires_explicit_nf4')
    if config.get('device_map') != 'auto':
        raise ValueError('cuda_pilot_requires_explicit_device_map_auto')
    if config.get('do_sample', False) or config.get('enable_thinking', False):
        raise ValueError('initial_cuda_pilot_is_greedy_non_thinking')


def validate_device_map(mapping):
    if not mapping:
        raise ValueError('missing_hf_device_map')
    for device in mapping.values():
        if not (isinstance(device, int) and device >= 0 or
                re.fullmatch(r'cuda(?::\d+)?', str(device))):
            raise ValueError('cpu_or_disk_offload_not_allowed_in_gpu_pilot')


class HuggingFaceCUDA:
    def __init__(self, config):
        check_config(config)
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        self.config, self.torch = config, torch
        if not torch.cuda.is_available():
            raise RuntimeError('cuda_required_no_cpu_fallback')
        count = torch.cuda.device_count()
        if count < config.get('min_gpus', 1):
            raise RuntimeError('insufficient_gpu_count')
        free = [torch.cuda.mem_get_info(i)[0] for i in range(count)]
        budget = memory_budget(free, config.get('reserve_gib_per_gpu', 2))
        if sum(budget.values()) < config.get('min_weight_budget_gib', 0) * 1024**3:
            raise RuntimeError('insufficient_gpu_weight_budget')
        options = dict(revision=config['revision'],
                       local_files_only=not config.get('allow_download', False),
                       trust_remote_code=False)
        self.tokenizer = AutoTokenizer.from_pretrained(config['model_id'], **options)
        self.model = AutoModelForCausalLM.from_pretrained(
            config['model_id'], **options, dtype=torch.float16,
            device_map='auto', max_memory=budget, attn_implementation='sdpa',
            quantization_config=BitsAndBytesConfig(
                load_in_4bit=True, bnb_4bit_quant_type='nf4',
                bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.float16),
        ).eval()
        validate_device_map(self.model.hf_device_map)
        self.input_device = self.model.get_input_embeddings().weight.device
        self.runtime = dict(
            quantization='nf4_double_quant', compute_dtype='float16',
            model_id=config['model_id'], revision=config['revision'],
            gpu_names=[torch.cuda.get_device_name(i) for i in range(count)],
            device_map={k: str(v) for k, v in self.model.hf_device_map.items()},
            max_memory_bytes=budget, cuda_version=torch.version.cuda,
            package_versions={name: importlib.metadata.version(name) for name in
                              ('torch', 'transformers', 'accelerate', 'bitsandbytes')},
            chat_template_sha256=hashlib.sha256(str(self.tokenizer.chat_template).encode()).hexdigest(),
            tokenization='apply_chat_template_tokenize_true_no_duplicate_special_tokens',
        )

    def complete(self, messages):
        torch, config = self.torch, self.config
        torch.manual_seed(config.get('seed', 20261104))
        inputs = self.tokenizer.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=True,
            return_tensors='pt', return_dict=True, enable_thinking=False,
        )
        length = inputs['input_ids'].shape[-1]
        if length > config.get('max_input_tokens', 4096):
            raise ValueError('input_too_long_no_truncation')
        inputs = inputs.to(self.input_device)
        for i in range(torch.cuda.device_count()):
            torch.cuda.reset_peak_memory_stats(i)
            torch.cuda.synchronize(i)
        with torch.inference_mode():
            tokens = self.model.generate(
                **inputs, max_new_tokens=config.get('max_new_tokens', 768), do_sample=False,
                pad_token_id=self.tokenizer.eos_token_id,
            )[0, length:]
        for i in range(torch.cuda.device_count()):
            torch.cuda.synchronize(i)
        eos = self.model.generation_config.eos_token_id
        eos_ids = set(eos if isinstance(eos, list) else [eos])
        raw = self.tokenizer.decode(tokens, skip_special_tokens=True)
        usage = dict(self.runtime, input_tokens=length, output_tokens=len(tokens),
                     ended_with_eos=bool(len(tokens) and tokens[-1].item() in eos_ids),
                     reached_token_budget=len(tokens) >= config.get('max_new_tokens', 768),
                     peak_allocated_bytes=[torch.cuda.max_memory_allocated(i)
                                           for i in range(torch.cuda.device_count())])
        return raw, usage

"""No provider credentials inferred. Network is opt-in; HF defaults cache-only."""
import json
import os
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

class Mock:
    def __init__(self, config): self.config = config
    def complete(self, messages):
        return json.dumps(dict(risk=None, predicted_class=None, severity=None,
            effect_summary='Mock abstention; no model inference.', evidence_spans=[],
            missing_context=['model_not_run'], review_required=True,
            reason_codes=['MOCK'], policy_refs=[])), {'mock': True}

class HuggingFace:
    def __init__(self, config):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from transformers.utils import logging
        logging.disable_progress_bar()
        self.config = config
        self.torch = torch
        self.device = config.get('device', 'cpu')
        revision = config.get('revision')
        if not revision: raise ValueError('Pin checkpoint revision or snapshot directory')
        options = dict(revision=revision, local_files_only=not config.get('allow_download', False), trust_remote_code=False)
        self.tokenizer = AutoTokenizer.from_pretrained(config['model_id'], **options)
        self.model = AutoModelForCausalLM.from_pretrained(config['model_id'], dtype=torch.float32 if self.device=='cpu' else torch.float16, **options).to(self.device).eval()
    def complete(self, messages):
        c = self.config
        self.torch.manual_seed(c.get('seed', 20261101))
        text = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True,
                                                  enable_thinking=c.get('enable_thinking', False))
        inputs = self.tokenizer(text, return_tensors='pt').to(self.device)
        if inputs.input_ids.shape[-1] > c.get('max_input_tokens', 8192):
            raise ValueError('input_too_long_no_truncation')
        options = dict(max_new_tokens=c.get('max_new_tokens', 600), do_sample=c.get('do_sample', False),
                       pad_token_id=self.tokenizer.eos_token_id)
        if options['do_sample']:
            options.update(temperature=c.get('temperature', 0.7), top_p=c.get('top_p', 0.8), top_k=c.get('top_k', 20))
        with self.torch.inference_mode():
            tokens = self.model.generate(**inputs, **options)[0, inputs.input_ids.shape[-1]:]
        return self.tokenizer.decode(tokens, skip_special_tokens=True), dict(input_tokens=inputs.input_ids.shape[-1], output_tokens=len(tokens), model_id=c['model_id'], revision=c['revision'], device=self.device)

class OpenAICompatible:
    """vLLM/llama.cpp/local servers; no vendor SDK or implicit paid API."""
    def __init__(self, config):
        self.config = config
        base = config['base_url'].rstrip('/')
        parsed = urlparse(base)
        if parsed.username or parsed.password or parsed.query:
            raise ValueError('credentials_or_query_in_url_forbidden')
        if parsed.hostname not in ('localhost','127.0.0.1','::1') and not config.get('allow_network', False):
            raise ValueError('external_network_requires_explicit_config')
        self.url = base + '/chat/completions'
    def complete(self, messages):
        c = self.config
        body = dict(model=c['model_id'], messages=messages, temperature=c.get('temperature',0),
                    max_tokens=c.get('max_new_tokens',600), response_format={'type':'json_object'})
        headers = {'Content-Type':'application/json'}
        if c.get('api_key_env'):
            key = os.environ.get(c['api_key_env'])
            if not key: raise ValueError('configured_api_key_missing')
            headers['Authorization'] = 'Bearer ' + key
        for attempt in range(c.get('transport_retries', 2)+1):
            try:
                req = urllib.request.Request(self.url, data=json.dumps(body).encode(), headers=headers)
                with urllib.request.urlopen(req, timeout=c.get('timeout',60)) as response:
                    result = json.load(response)
                return result['choices'][0]['message']['content'], result.get('usage',{})
            except urllib.error.HTTPError as exc:
                if exc.code not in (429,500,502,503,504) or attempt == c.get('transport_retries',2):
                    # Never print response bodies, headers or credentials.
                    raise RuntimeError(f'provider_http_{exc.code}') from None
                time.sleep(min(2**attempt, 8))

def make_adapter(config):
    return {'mock':Mock, 'huggingface':HuggingFace, 'openai_compatible':OpenAICompatible}[config['provider']](config)

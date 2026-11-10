from typing import Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class PipelineConfig(StrictModel):
    stage1_concurrency: int = Field(default=8, ge=1, le=128)
    stage2_concurrency: int = Field(default=8, ge=1, le=128)
    max_inflight_total: int = Field(default=16, ge=1, le=256)
    queue_capacity: int = Field(default=128, ge=1, le=10000)
    prefer_stage2_when_backlogged: bool = True
    max_format_retries: int = Field(default=2, ge=0, le=2)
    max_transport_retries: int = Field(default=3, ge=0, le=10)
    request_timeout_seconds: float = Field(default=180, gt=0)
    backoff_base_seconds: float = Field(default=1, gt=0)
    max_retry_wait_seconds: float = Field(default=300, gt=0)


class RateConfig(StrictModel):
    requests_per_minute: int | None = Field(default=None, gt=0)
    input_tokens_per_minute: int | None = Field(default=None, gt=0)
    output_tokens_per_minute: int | None = Field(default=None, gt=0)
    combined_tokens_per_minute: int | None = Field(default=None, gt=0)
    utilization_target: float = Field(default=0.75, gt=0, le=1)


class InferenceConfig(StrictModel):
    provider: Literal['mock', 'openai_compatible'] = 'mock'
    model_id: str = 'mock-fixtures-v1'
    model_revision: str = '1'
    base_url: str | None = None
    api_key_env: str = 'CODEGUARD_API_KEY'
    allow_network: bool = False
    reasoning_effort: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    seed: int | None = None
    completion_token_parameter: Literal['max_completion_tokens', 'max_tokens'] = 'max_completion_tokens'
    structured_output: Literal['json_schema', 'json_object', 'none'] = 'json_schema'
    max_input_tokens: int = Field(default=100000, gt=0)
    reserved_output_tokens_stage1: int = Field(default=1200, gt=0)
    reserved_output_tokens_stage2: int = Field(default=600, gt=0)
    input_price_per_million: float = Field(default=0, ge=0)
    output_price_per_million: float = Field(default=0, ge=0)
    currency: str = 'USD'
    mock_latency_seconds: float = Field(default=0.005, ge=0)


class RunConfig(StrictModel):
    max_spend: float | None = Field(default=None, ge=0)
    cache_policy: Literal['off', 'exact'] = 'off'
    metrics_interval_seconds: float = Field(default=30, gt=0)


class Config(StrictModel):
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    rate_limit: RateConfig = Field(default_factory=RateConfig)
    inference: InferenceConfig = Field(default_factory=InferenceConfig)
    run: RunConfig = Field(default_factory=RunConfig)

    @model_validator(mode='after')
    def network_gate(self):
        i = self.inference
        if i.base_url:
            url = urlsplit(i.base_url)
            if url.username or url.password or url.query or url.fragment:
                raise ValueError('credentials/query/fragment forbidden in endpoint')
        if i.provider != 'mock':
            if not i.allow_network or self.run.max_spend is None or self.run.max_spend <= 0:
                raise ValueError('network requires allow_network and explicit positive max_spend')
            if not i.base_url or i.input_price_per_million <= 0 or i.output_price_per_million <= 0:
                raise ValueError('configure endpoint and positive input/output prices')
        return self

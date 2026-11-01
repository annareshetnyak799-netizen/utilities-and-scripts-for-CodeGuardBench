# CodeGuardBench — D3 judge и генерация кандидатов

Рабочая ветка `feat/d3-judge-pipeline`. Вспомогательная разметка Bash-команд,
не production guard и не автоматический gold. Подробные команды — [RUNBOOK](RUNBOOK.md).

- [Политика v0](policy/POLICY_V0.md), версионированные промпты и строгий JSON.
- `judge.pipeline`: command-only вход, локальные HF/open-compatible модели,
  resume, статические проверки, disagreement/review gate.
- `judge.generate`: раздельные seeds и синтетические кандидаты, без few-shot
  из реальных источников; автоматического включения в test/train нет.
- `judge.dataset`: схема9полей, provenance gate, exact/near/family overlap,
  экспорт отдельно принятых человеком записей.
- `judge.select_val`: разделение по семействам и признакам сложности.
- [Ресёрч моделей](reports/JUDGE_MODEL_RESEARCH.md), [прогресс](reports/PROGRESS.md),
  [следующие шаги](reports/NEXT_STEPS.md).

Данные CAT-2 находятся в репозитории [SfBalaba/code_guard_benchmark](https://github.com/SfBalaba/code_guard_benchmark), в четырёх отдельных ветках `feat/data_CAT-2.N`.
После текущего этапа там175 строк (31/69/35/40), не gold; квота250/риск не закрыта.
80 test seed drafts — не80 проверенных независимых семейств. Train-черновики
хранятся вне тестового репозитория; в код/промпты не включаются реальные команды
для генерации train. Ни одна команда корпуса не исполняется.

Метрики пилота в reports — согласие с агентскими proposals, не human-gold
accuracy. HF decoding здесь без гарантии JSON grammar; валидатор отклоняет
ошибки, а не чинит их присвоением ask. Платные API по умолчанию отключены.

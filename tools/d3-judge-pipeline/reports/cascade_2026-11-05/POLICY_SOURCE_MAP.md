# Источники политики и трассировка

Registry: `codeguard_judge/data/policy.json`; сборка `scripts/build_policy_registry.py`. Prompts компилируются `compile_policy()`, а не поддерживаются параллельным перечнем правил.

| Файл | SHA256 | Роль |
|---|---|---|
| evidence/guideline.md | 5c17579d15f62c225f11e386bb11aa410ad7aa3ceac65b2aab992a88f2b70737 | Первичный Guideline |
| evidence/pr1_comments.json | 683a5105ce55b18bcf5256716f574a0b6a03c063f96d5c6a037dac8f881c428b | Прямые комментарии Софьи, совпали с live 05.11 |
| evidence/authorization.md | 3882f85d0f62cdf186f4215a8c0f376699e6bf18ec310ad3eb574c9e6ab8eff4 | Зафиксированные поздние ограничения v0 |
| evidence/night_spec_2026-11-05.md | cbbd4c567e40b3871eff3a4c5e407c3a8de4673a1b7fb757ee6feece6e40b124 | Текущее задание; proposed binary contract |

| Risk | Линии Guideline | Status |
|---|---|---|
| CAT-0.0 | 31–39 | active definition; old modify/defer defaults unresolved where present |
| CAT-1.1 | 42–49 | active definition; old modify/defer defaults unresolved where present |
| CAT-1.2 | 50–57 | active definition; old modify/defer defaults unresolved where present |
| CAT-1.3 | 58–65 | active definition; old modify/defer defaults unresolved where present |
| CAT-1.4 | 66–73 | active definition; old modify/defer defaults unresolved where present |
| CAT-1.5 | 74–83 | active definition; old modify/defer defaults unresolved where present |
| CAT-2.1 | 86–93 | active definition; old modify/defer defaults unresolved where present |
| CAT-2.2 | 94–101 | active definition; old modify/defer defaults unresolved where present |
| CAT-2.3 | 102–109 | active definition; old modify/defer defaults unresolved where present |
| CAT-2.4 | 110–119 | active definition; old modify/defer defaults unresolved where present |
| CAT-3.1 | 122–129 | active definition; old modify/defer defaults unresolved where present |
| CAT-3.2 | 130–137 | active definition; old modify/defer defaults unresolved where present |
| CAT-3.3 | 138–145 | active definition; old modify/defer defaults unresolved where present |
| CAT-3.4 | 146–153 | active definition; old modify/defer defaults unresolved where present |
| CAT-3.5 | 154–163 | active definition; old modify/defer defaults unresolved where present |
| CAT-4.1 | 166–173 | active definition; old modify/defer defaults unresolved where present |
| CAT-4.2 | 174–181 | active definition; old modify/defer defaults unresolved where present |
| CAT-4.3 | 182–189 | active definition; old modify/defer defaults unresolved where present |
| CAT-4.4 | 190–197 | active definition; old modify/defer defaults unresolved where present |
| CAT-4.5 | 198–207 | active definition; old modify/defer defaults unresolved where present |
| CAT-5.1 | 210–217 | active definition; old modify/defer defaults unresolved where present |
| CAT-5.2 | 218–225 | active definition; old modify/defer defaults unresolved where present |
| CAT-5.3 | 226–233 | active definition; old modify/defer defaults unresolved where present |
| CAT-5.4 | 234–241 | active definition; old modify/defer defaults unresolved where present |
| CAT-5.5 | 242–251 | active definition; old modify/defer defaults unresolved where present |
| CAT-6.1 | 254–261 | active definition; old modify/defer defaults unresolved where present |
| CAT-6.2 | 262–269 | active definition; old modify/defer defaults unresolved where present |
| CAT-6.3 | 270–277 | active definition; old modify/defer defaults unresolved where present |
| CAT-6.4 | 278–285 | active definition; old modify/defer defaults unresolved where present |
| CAT-6.5 | 286–295 | active definition; old modify/defer defaults unresolved where present |
| CAT-7.1 | 298–305 | active definition; old modify/defer defaults unresolved where present |
| CAT-7.2 | 306–313 | active definition; old modify/defer defaults unresolved where present |
| CAT-7.3 | 314–321 | active definition; old modify/defer defaults unresolved where present |
| CAT-7.4 | 322–329 | active definition; old modify/defer defaults unresolved where present |
| CAT-7.5 | 330–339 | active definition; old modify/defer defaults unresolved where present |
| CAT-8.1 | 342–349 | active definition; old modify/defer defaults unresolved where present |
| CAT-8.2 | 350–357 | active definition; old modify/defer defaults unresolved where present |
| CAT-8.3 | 358–367 | active definition; old modify/defer defaults unresolved where present |
| CAT-9.1 | 370–377 | active definition; old modify/defer defaults unresolved where present |
| CAT-9.2 | 378–385 | active definition; old modify/defer defaults unresolved where present |
| CAT-9.3 | 386–393 | active definition; old modify/defer defaults unresolved where present |
| CAT-9.4 | 394–403 | active definition; old modify/defer defaults unresolved where present |

Приоритет: V0/наблюдаемость → прямые указания лида → условные карточки. Binary mapping proposed и не объявлен правилом Софьи. Все 42 определения, exclusions, templates и controls хранятся буквально. Это покрытие registry, не доказательство исполнимости всех правил.

Старый POLICY_V0.md и system_v1.md остаются legacy baseline, не источником новых категорий. Старые defaults внутри карт не удалены: их конфликт с v0 явно отмечен. Автоматического преобразования modify/defer нет.


## Правила проекта

- **Версии**: перед каждой сборкой (`npm run tauri build`) поднимать patch-версию в ОБОИХ файлах: `src-tauri/tauri.conf.json` и `src-tauri/Cargo.toml`.
- **CHANGELOG.md**: обновлять при каждом событии — локальная пересборка, коммит, `gh release create`. Добавлять новую запись в начало файла с версией, датой и кратким описанием изменений.

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
- Author a backlog-ready spec/issue → invoke /spec

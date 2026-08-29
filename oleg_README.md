# Продукт Олега

Три папки в корне репозитория работают вместе:

- `oleg_engine/` — собирает реестр обязательств из входящих файлов;
- `oleg_pipeline/` — прогоняет любую папку примеров через любой движок и оценивает результат по смыслу;
- `oleg_web/` — показывает реестр, запускает движок и сохраняет ручные правки.

`cli.py` комнаты для этого продукта не нужен.

## Быстрый запуск из свежего клона

Нужен `codex` или `claude` CLI в `PATH`.

```bash
pip install fastapi uvicorn
python -m oleg_web
# Выберите пример на странице и нажмите «Прогнать».
python -m oleg_pipeline run --examples examples --engine "python -m oleg_engine run --input {input} --registry {registry}"
```

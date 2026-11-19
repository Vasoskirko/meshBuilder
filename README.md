# meshBuilder

Генератор структурированных сеток для CFD-расчётов пучков стержней (ТВС) с треугольной решёткой и интеграцией со STAR-CCM+.

## Установка зависимостей

```bash
pip install -r requirements.txt
```

## Запуск

- **Графический интерфейс (GUI):**
  ```bash
  python mesh_gui.py
  ```
- **Консольный режим (CLI):**
  ```bash
  python mesh_core.py --help
  ```

## Основные модули

- `mesh_gui.py` — графический интерфейс (PySide6) и визуализация.
- `mesh_core.py` — расчёт сетки, законы распределения, независимый пристеночный слой и CLI.
- `mesh_quality.py` — расчёт и интерпретация метрик качества сетки.
- `mesh_project.py` — сохранение и загрузка проектов (`.json`).
- `bundle_geometry.py`, `bundle_subchannel_builder.py`, `mesh_subchannel.py` — подканальная геометрия и построение.
- `fluid_properties.py`, `yplus_calculator.py` — свойства теплоносителя и расчёт `y+`.
- `starccm_macro_generator.py`, `setup_starccm_subchannels.java` — генерация макросов для STAR-CCM+.

## Свойства воды

Для жидкой воды используются IF97 (регион 1), вязкость IAPWS 2008 и теплопроводность IAPWS 2011 с явным выбором критического усиления через `iapws==1.5.5`.
После обновления установите зависимости из `requirements.txt`.
Диапазон, единицы, контрольные значения и ограничения описаны в [docs/water_transport.md](docs/water_transport.md).

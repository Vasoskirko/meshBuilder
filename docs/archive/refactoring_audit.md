> Архивировано 23 ноября 2026 года. Исторический отчёт для указанных в нём коммитов; статусы проверок и список ограничений не описывают текущую версию. Актуальная документация: [README проекта](../../README.md).

# Refactoring audit

No full manual review of all project files is certified yet. Prior merges were not backed by executed tests.

## Automated checks

Run `python -m unittest discover -s tests -v` with project requirements installed and full Git history available. Set `QT_QPA_PLATFORM=offscreen` for headless runs.

The baseline for core numerical regression is commit `fc044b9a2f7c7408cf664b7fb9e17e12619cb726`. Tests compare coordinates, widths, diagnostics and XYZ bytes. They also check layer preservation, configuration round trips, incomplete-export rejection, module imports, CLI help and GUI construction.

CI emits a CSV inventory of every tracked Python file, including commit SHA, size, lines and AST symbol counts. Inventory is NOT evidence of manual semantic review. No test run is claimed successful until CI results are inspected.

## Pending coverage and review

- Full semantic review of mesh_gui.py and bundle_subchannel_builder.py, including code after their main guards in the historical versions.
- Regression comparison for GUI method inventories and signal wiring against the baseline.
- Detailed review of mesh_ui.py, mesh_quality.py, starccm_macro_generator.py, mesh_subchannel_subpanel.py, mesh_subchannel.py and bundle_geometry.py.
- Invalid-input tests, legacy configuration migration, project/workflow state transitions and quality dialog interaction.
- STAR-CCM+ Java macro validation in the target solver environment.
- Independent numerical validation: agreement with the baseline does not prove mathematical correctness.

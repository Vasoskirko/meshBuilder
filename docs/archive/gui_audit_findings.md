> Архивировано 23 ноября 2026 года. Исторический отчёт для указанных в нём коммитов; статусы проверок и список ограничений не описывают текущую версию. Актуальная документация: [README проекта](../../README.md).

# GUI audit checkpoint

## Scope and evidence

Baseline: fc044b9a2f7c7408cf664b7fb9e17e12619cb726. The supplied GUI report has head 7ff9aff1a6122a1cbf3fafbcf9472ad419bb1e4d, a GitHub-generated merge of e2ceee9 into 150f872. It is not an audit of every project file.

In that report, mesh_gui.py has 70 shared symbol names with unchanged definitions, 15 removed symbol names belonging to extracted dialogs, and no changed shared symbols. bundle_subchannel_builder.py has 37 unchanged shared symbol names, six changed shared symbols, and three removed HydraulicsTableDialog symbols. No top-level statements follow the first main guard in either version of either file. Property getter/setter pairs result and stale are not erroneous duplicates.

## Reviewed changes

The diff of d2e0b5ef4e0f4dd161efd80923640e10b26a1439 explains all six changed BundleBuilderWindow methods: removal of unused btn_no bindings in two rod-edit handlers; removal of an immediately overwritten current_layer_result assignment; removal of an unused params binding in redraw_mesh_views; relocation of quality-dialog imports; and the new import path for StarCcmExportDialog. No regression was identified in those edits by source inspection. This is not runtime certification.

All six HelpDialog methods and all three HydraulicsTableDialog methods were located in extracted modules, along with their respective signal connections. QualityDialog has eight of its former nine methods: _brush was inlined as QBrush(QColor(color)) at both call sites. Full automated cross-module AST equivalence has not been established.

## Reproduced export defects and fix

At 7917b848c4a64ffd67351de1cf4052e24507fb77, the supplied CI log shows 14 test methods: 12 passed, one failed on overwritten identical output paths, and one errored on an uncaught synthetic Java-generator exception.

Commit c336b31ded284cac8ea396c6bb72429bde12893e changes only starccm_export_dialog.py: output-path collision checks precede export, and Java-generation exceptions produce an error message and return without accepting the dialog. The message explicitly states that XYZ has already been exported. Tests were not weakened.

Both tests checks and both compare checks reported success for that PR head. Evidence: https://github.com/Vasoskirko/meshBuilder/actions/runs/44081433914/job/134032733095 and https://github.com/Vasoskirko/meshBuilder/actions/runs/44081433702/job/134032730439 . The compare job succeeding means report generation succeeded, not that all differences are safe.

## Remaining limitations

- Export tests mock the Plot3D exporter and Java generator; they do not validate solver execution or actual output formats.
- Pairwise XYZ/Java writes are not atomic. An XYZ file can remain after generation failure; partial writes and rollback are not covered.
- Symlink and hard-link collision handling exists but currently lacks dedicated tests. Path checks are not race-proof.
- UI height versus built-mesh height consistency remains unverified.
- Saving quality reports through the bundle parent, profile editing, project transitions, and detailed user interactions remain to be tested.
- Full semantic review of extracted modules, core mathematics and STAR-CCM+ macro compatibility is not certified.

The original [refactoring_audit.md](refactoring_audit.md) is an initial inventory; this checkpoint supplements it and does not certify completion of its pending items.

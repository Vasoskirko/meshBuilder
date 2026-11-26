"""Bridge from the unified window to the existing staged reference exporter."""
from copy import deepcopy
from pathlib import Path
from PySide6.QtWidgets import QFileDialog,QMessageBox
from starccm_tmc_export import (TMC_DEFAULTS,validate_tmc_settings,canonical_tmc_options,
    reference_geometry,write_tmc_bundle)
from starccm_export_profile import DEFAULTS,validate_options
from starccm_workflow import validate_workflow


def tdc_options(d,workflow):
    if not d.rb_inter_fuse.isChecked() or not d.rb_turb_srh.isChecked() or d.rb_eos_iapws.isChecked():
        raise ValueError('TDC требует Fuse, HYBRID · SRH / SST и постоянные свойства. Настройки физики не меняются автоматически.')
    if not workflow['tdc_equivalence']:raise ValueError('Подтвердите допущение трёх эквивалентных зазоров эталона TDC')
    if not d.chk_thermal.isChecked():raise ValueError('Для TDC включите энергию')
    if not d.rb_wall_60.isChecked():raise ValueError('Для эталона TDC сохраните исходные rod-секторы')
    fluid=d.read_fluid();settings=deepcopy(TMC_DEFAULTS)
    for key,field in d.tmc_fields.items():
        settings[key]=field.isChecked() if type(TMC_DEFAULTS[key]) is bool else field.value()
    settings.update(rho=fluid['density'],mu=fluid['dyn_vis'],cp=fluid['cp'],conductivity=fluid['lambda'],
        temperature_ref=workflow['initial_temperature'],time_step=d.field_time_step.value(),
        hydro_duration=workflow['warmup_duration'],thermal_duration=workflow['warmup_duration'],
        block_duration=workflow['block_duration'],blocks_to_run=workflow['blocks_per_run'])
    settings=validate_tmc_settings(settings)
    values=deepcopy(DEFAULTS);values.update(canonical_tmc_options(settings))
    values.update(export_mode='tmc_reference',tmc_settings=settings,workflow=workflow,
        create_quality_scene=workflow['quality_enabled'] and d.chk_scene.isChecked(),
        create_quality_histograms=workflow['quality_enabled'] and d.chk_histograms.isChecked(),
        create_bad_cells=workflow['quality_enabled'] and d.chk_bad_cells.isChecked(),quality_bins=d.spin_quality_bins.value())
    return validate_options(values,d.sub_count)


def export_tdc(d):
    from mesh_export_jobs import run_export,ExportCancelled
    try:
        options=d.read_options();reference_geometry(d.mesh_result,d.bundle_model)
        from starccm_tmc_export import bundle_names
        xyz=d.edit_xyz.text().strip();bundle_names(xyz)
    except (ValueError,TypeError) as exc:QMessageBox.warning(d,'Проверьте TDC',str(exc));return
    parent=d.parent()
    if parent is not None and hasattr(parent,'can_export_mesh') and (not parent.can_export_mesh() or parent.current_mesh_result is not d.mesh_result):
        QMessageBox.warning(d,'Экспорт недоступен','Сетка устарела; перестройте её.');return
    directory=QFileDialog.getExistingDirectory(d,'Папка комплекта TDC')
    if not directory:return
    names=(xyz,'setup_starccm_subchannels.java','TDC_Hybrid.java','TDC_export.json','TDC_START.txt','TDC_analyse_series.py')
    existing=[name for name in names if (Path(directory)/name).exists()]
    if existing and QMessageBox.question(d,'Заменить файлы?', '\n'.join(existing),QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:return
    result=d.mesh_result;model=deepcopy(d.bundle_model);settings=deepcopy(options['tmc_settings'])
    def compute(progress):return write_tmc_bundle(directory,xyz,result,model,settings,progress,unified_options=options)
    def success(paths):
        QMessageBox.information(d,'Комплект TDC создан','\n'.join(map(str,paths))+'\nПорядок запуска: TDC_START.txt.');d.accept()
    def failure(exc):
        if not isinstance(exc,ExportCancelled):QMessageBox.critical(d,'Ошибка экспорта TDC',str(exc))
    run_export(d,'Экспорт TDC',compute,success,failure)

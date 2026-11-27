"""Presentation of cached geometry diagnostics in the section editor."""
from copy import deepcopy
from PySide6.QtCore import Qt

from PySide6.QtWidgets import QLabel,QPushButton,QCheckBox,QMessageBox

AUTO_DIAGNOSTIC_LIMIT=300


def install(owner):
    layout=owner.summary_text.parentWidget().layout()
    owner.geometry_status=QLabel();owner.geometry_status.setWordWrap(True);owner.geometry_status.setTextFormat(Qt.PlainText)
    layout.insertWidget(0,owner.geometry_status)
    button=QPushButton('Проверка геометрии и подробности');owner.geometry_check_button=button;layout.insertWidget(1,button)
    owner.geometry_show_problems=QCheckBox('Подсветить возможные дыры и перекрытия');layout.insertWidget(2,owner.geometry_show_problems)
    owner.geometry_show_problems.setToolTip('Красный — непокрытая жидкость; оранжевый — перекрытие. Показаны до 20 внешних контуров каждого вида. Учитывайте интервалы погрешности в подробностях.')
    owner.geometry_show_problems.toggled.connect(lambda _:owner.rebuild_view())
    def show():
        if len(owner.model.subchannels)>AUTO_DIAGNOSTIC_LIMIT and getattr(owner.model,'_diagnostics_cache',None) is None:
            try:from .diagnostics import diagnose
            except ImportError:
                QMessageBox.information(owner,'Геометрия сечения','Установите зависимости из requirements.txt (Shapely).');return
            original=owner.model;snapshot=deepcopy(original)
            def compute(progress):return diagnose(snapshot,progress=progress)
            def completed(report):
                if owner.model is original:
                    original._diagnostics_cache=report;owner.rebuild_view()
                    QMessageBox.information(owner,'Геометрия сечения',report.text())
            try:owner._run_mesh_task('Проверка геометрии',compute,completed,'Проверка геометрии')
            except ValueError as error:QMessageBox.warning(owner,'Проверка геометрии','Завершите ввод параметров перед запуском проверки.\n'+str(error))
            return
        try:text=owner.model.get_geometry_diagnostics().text()
        except ImportError:text='Проверка недоступна. Установите зависимости из requirements.txt (Shapely).'
        QMessageBox.information(owner,'Геометрия сечения',text)
    button.clicked.connect(show)


def refresh(owner):
    if not hasattr(owner,'geometry_status'):return None
    if len(owner.model.subchannels)>AUTO_DIAGNOSTIC_LIMIT and getattr(owner.model,'_diagnostics_cache',None) is None:
        owner.geometry_status.setStyleSheet('QLabel {background:#fff4dc;padding:7px;}')
        owner.geometry_status.setText('Большая геометрия: проверка ещё не выполнена. Нажмите «Проверка геометрии и подробности»; она выполняется в фоне.')
        return None
    try:report=owner.model.get_geometry_diagnostics()
    except ImportError:
        owner.geometry_status.setText('Проверка геометрии недоступна: установите зависимости из requirements.txt (Shapely).')
        return None
    color={'ok':'#e8f5e9','uncertain':'#fff4dc','error':'#ffebe9'}[report.status]
    owner.geometry_status.setStyleSheet(f'QLabel {{background:{color};padding:7px;border-radius:4px;}}')
    lines=report.text().splitlines()[:3]
    if report.collisions or report.wall_collisions or report.invalid_subchannels or report.hydraulic_mismatches:
        lines.append(f'Пересечений стержней: {len(report.collisions)}; с оболочкой: {len(report.wall_collisions)}; проблемных площадей: {len(report.hydraulic_mismatches)}; полигонов: {len(report.invalid_subchannels)}. См. подробности.')
    owner.geometry_status.setText('\n'.join(lines))
    if owner.geometry_show_problems.isChecked():
        for rings,color in ((report.gap_outlines,'#c62828'),(report.overlap_outlines,'#ef6c00')):
            for ring in rings:
                x,y=zip(*ring);owner.ax.plot(x,y,color=color,linewidth=2.5,zorder=9)
    return report


def label_point(model,sid):
    if len(model.subchannels)>AUTO_DIAGNOSTIC_LIMIT and getattr(model,'_diagnostics_cache',None) is None:return model.subchannels[sid].fluid_center
    try:
        report=model.get_geometry_diagnostics()
        # Cache the lookup outside hot plotting loops; immutable diagnostics owns tuples.
        if getattr(model,'_label_point_report',None) is not report:
            model._label_point_report=report;model._label_point_lookup=dict(report.label_points)
        return model._label_point_lookup.get(sid,model.subchannels[sid].fluid_center)
    except ImportError:return model.subchannels[sid].fluid_center

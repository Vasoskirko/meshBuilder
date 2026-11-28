"""Mesh forecasts and bounded visual diagnostics; display state never opens export."""
from copy import deepcopy
import numpy as np
from matplotlib.collections import PolyCollection
from matplotlib.patches import Polygon
from matplotlib.path import Path
from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QMessageBox
from bundle_project import commit_active_inputs
from bundle_mesh_preview import forecast,format_forecast,size_text
from mesh_visual_diagnostics import diagnose,describe,METRICS

class BundleDiagnosticsMixin:
    def on_estimate_mesh(self):
        if self._project_busy():return
        try:
            commit_active_inputs(self)
            if not self.model.selected_subchannels:raise ValueError('Выберите подканалы для оценки')
            p=self.mesh_subpanel;f=p.fields
            model=deepcopy(self.model);base=self.base_params
            templates=deepcopy(self.template_configs);overrides=deepcopy(self.block_custom_configs)
            from bundle_block_editor import core_state
            data=getattr(p,'_global_core_state',None)
            if data is None:data=core_state(p)
            core=dict(mode=data['local_core_mode'],growth=data['local_core_growth'],size=data['local_core_size'],
                      limit=data['local_core_limit'],layers=data['local_core_layers'],transition=data['local_core_transition'])
            layer=self.current_layer_result
            def compute(progress):return forecast(model,base,templates,overrides,core,layer,progress)
            def completed(data):
                self.append_mesh_message(format_forecast(data))
                if self._mesh_variant_a is not None:self.append_mesh_message(f'Дополнительно удерживается вариант A: минимум {size_text(self._mesh_variant_a["coordinates_bytes"])} координат 2D.')
            self._run_mesh_task('Оценка размера сетки',compute,completed,'Не удалось оценить сетку')
        except Exception as exc:
            self.append_mesh_message(f'Оценка сетки: {exc}')
            QMessageBox.warning(self,'Оценка сетки',str(exc))

    def on_diagnostic_metric_changed(self,*args):
        spec=METRICS[self.combo_mesh_diagnostic.currentData()]
        with QSignalBlocker(self.spin_diagnostic_threshold):
            self.spin_diagnostic_threshold.setRange(spec['minimum'],spec['maximum'])
            self.spin_diagnostic_threshold.setValue(spec['default'])
            self.spin_diagnostic_threshold.setSuffix(spec['unit'])
        self.spin_diagnostic_threshold.setToolTip('Выделяются значения '+spec['symbol']+' порога; невалидные ячейки выделяются всегда.')
        self.clear_mesh_diagnostics()

    def clear_mesh_diagnostics(self,*args):
        self._mesh_diagnostic=None;self._selected_diagnostic=None
        if not hasattr(self,'ax_mesh'):return
        for artist in [*self.ax_mesh.collections,*self.ax_mesh.patches]:
            if artist.get_gid() in ('mesh-diagnostic','mesh-diagnostic-selected') or (self.current_mesh_result is None and artist.get_gid()=='mesh-variant-a'):artist.remove()
        if hasattr(self,'btn_mesh_diagnostic'):self.btn_mesh_diagnostic.setEnabled(self.current_mesh_result is not None)
        self.canvas_mesh.draw_idle()

    def on_mesh_diagnostic(self):
        if self._project_busy():return
        self.validate_mesh_inputs()
        result=self.current_mesh_result
        if result is None:
            QMessageBox.warning(self,'Подсветка','Сначала постройте актуальную сетку или пристеночный слой.');return
        metric=self.combo_mesh_diagnostic.currentData();threshold=self.spin_diagnostic_threshold.value()
        def compute(progress):return diagnose(result,metric,threshold,progress=progress)
        def completed(data):
            if self.current_mesh_result is not result or self.combo_mesh_diagnostic.currentData()!=metric or self.spin_diagnostic_threshold.value()!=threshold:
                self.append_mesh_message('Настройки подсветки изменились; результат отброшен.');return
            data['mesh']=result;self._mesh_diagnostic=data;self._selected_diagnostic=None
            self.append_mesh_message(describe(data,result.params.nz))
            if self.chk_mesh_diagnostic.isChecked():self.redraw_mesh_views()
            else:self.chk_mesh_diagnostic.setChecked(True)
        self._run_mesh_task('Диагностика сечения',compute,completed,'Не удалось проверить сечение')

    def draw_mesh_diagnostics(self):
        self.btn_mesh_diagnostic.setEnabled(self.current_mesh_result is not None)
        data=getattr(self,'_mesh_diagnostic',None)
        if not self.chk_mesh_diagnostic.isChecked() or not data or data['mesh'] is not self.current_mesh_result:return
        if data['records']:
            polygons=[np.array(row['corners'])*1e3 for row in data['records']]
            overlay=PolyCollection(polygons,facecolors='#ef6c00',edgecolors='#d84315',linewidths=.6,alpha=.35,zorder=4)
            overlay.set_gid('mesh-diagnostic');self.ax_mesh.add_collection(overlay)
        self.draw_diagnostic_selection()

    def draw_diagnostic_selection(self):
        for patch in list(self.ax_mesh.patches):
            if patch.get_gid()=='mesh-diagnostic-selected':patch.remove()
        row=getattr(self,'_selected_diagnostic',None)
        if row is not None and self.chk_mesh_diagnostic.isChecked():
            patch=Polygon(np.array(row['corners'])*1e3,closed=True,fill=False,edgecolor='red',linewidth=2,zorder=6)
            patch.set_gid('mesh-diagnostic-selected');self.ax_mesh.add_patch(patch)

    def on_diagnostic_click(self,event):
        data=getattr(self,'_mesh_diagnostic',None)
        if (not data or data['mesh'] is not self.current_mesh_result or not self.chk_mesh_diagnostic.isChecked()
                or self.ruler_active or getattr(self.toolbar_mesh,'mode','') or event.inaxes is not self.ax_mesh
                or event.button!=1 or event.xdata is None or event.ydata is None):return
        for row in data['records']:
            poly=np.array(row['corners'])*1e3
            if Path(np.vstack((poly,poly[0]))).contains_point((event.xdata,event.ydata)):
                self._selected_diagnostic=row;self.draw_diagnostic_selection();self.canvas_mesh.draw_idle()
                m=row['metrics'];block=row['block'];result=data['mesh']
                source=f'; подканал S{result.instances_map[block][0]}' if block<len(result.instances_map) else ''
                self.append_mesh_message(f'ЯЧЕЙКА: блок {block+1}{source}; i={row["i"]+1}, j={row["j"]+1}; от стенки №{row["normal_cell"]}.\n'
                    f'Якобиан формы: {m["jacobian"]:.5g}; угловое отклонение: {m["angle"]:.3g}°.\n'
                    f'Пропорции в сечении: {m["aspect"]:.4g}; перепад объёмов внутри блока: {m["transition"]:.4g}.\n'
                    f'Объём одной 3D-ячейки: {m["volume"]:.5g} м³; одинаковые показатели для осевых слоёв 1…{result.params.nz}.')
                return

    def _comparison_geometry(self):
        from bundle_project import geometry
        return geometry(self.model)

    def _mesh_variant_summary(self):
        result=self.current_mesh_result
        metrics=(self.current_quality_report or {}).get('metrics',{})
        return dict(cells=sum((x.shape[0]-1)*(x.shape[1]-1)*result.params.nz for x,y in result.blocks),
            blocks=len(result.blocks),complete=result.complete,nz=result.params.nz,height=result.params.z_len,
            jacobian=metrics.get('scaled_jacobian',{}).get('min'),
            angle=(metrics['skewness']['max']*90 if metrics.get('skewness',{}).get('max') is not None else None),
            aspect=metrics.get('aspect_ratio',{}).get('max'))

    def remember_mesh_variant(self):
        if self._project_busy():return
        self.validate_mesh_inputs()
        if self.current_mesh_result is None:
            QMessageBox.warning(self,'Вариант A','Сначала постройте актуальную сетку.');return
        result=self.current_mesh_result
        self._mesh_variant_a=dict(mesh=result,summary=self._mesh_variant_summary(),geometry=self._comparison_geometry(),
                                 coordinates_bytes=sum(x.nbytes+y.nbytes for x,y in result.blocks))
        self.chk_mesh_variant_a.setEnabled(True)
        self.append_mesh_message(f'Вариант A запомнен: {self._mesh_variant_a["summary"]["cells"]:,} ячеек. '
            f'Удерживаются дополнительные данные: минимум {size_text(self._mesh_variant_a["coordinates_bytes"])} координат 2D плюс связанные данные результата. Очистите A, чтобы освободить их.')
        if self.chk_mesh_variant_a.isChecked():self.redraw_mesh_views()
        else:self.chk_mesh_variant_a.setChecked(True)

    def clear_mesh_variant(self):
        self._mesh_variant_a=None
        for artist in list(self.ax_mesh.collections):
            if artist.get_gid()=='mesh-variant-a':artist.remove()
        self.canvas_mesh.draw_idle()
        self.chk_mesh_variant_a.setChecked(False);self.chk_mesh_variant_a.setEnabled(False)
        if self.current_mesh_result is not None:self.redraw_mesh_views()

    def comparison_point_count(self):
        variant=getattr(self,'_mesh_variant_a',None)
        if not variant or not self.chk_mesh_variant_a.isChecked() or variant['geometry']!=self._comparison_geometry():return 0
        return sum(x.size for x,y in variant['mesh'].blocks)

    def draw_mesh_comparison(self,render_stride):
        if not self.comparison_point_count():return
        from matplotlib.collections import LineCollection
        for x,y in self._mesh_variant_a['mesh'].blocks:
            ii=np.unique(np.r_[np.arange(0,x.shape[0],render_stride),x.shape[0]-1])
            jj=np.unique(np.r_[np.arange(0,x.shape[1],render_stride),x.shape[1]-1])
            lines=[np.column_stack((x[i,jj],y[i,jj]))*1e3 for i in ii]+[np.column_stack((x[ii,j],y[ii,j]))*1e3 for j in jj]
            artist=LineCollection(lines,colors='#777777',linestyles='dashed',linewidths=.8,alpha=.7,zorder=1.5)
            artist.set_gid('mesh-variant-a');self.ax_mesh.add_collection(artist)

    def compare_mesh_variant(self):
        self.validate_mesh_inputs()
        variant=getattr(self,'_mesh_variant_a',None)
        if not variant or self.current_mesh_result is None:
            QMessageBox.warning(self,'Сравнение','Запомните вариант A, затем постройте актуальный вариант B.');return
        a,b=variant['summary'],self._mesh_variant_summary()
        def value(x):return '—' if x is None else f'{x:,.5g}'
        lines=['СРАВНЕНИЕ СЕТОК',f'{"Показатель":<30} {"A":>14} {"B (текущая)":>14}','─'*62]
        for label,key in (('Ячейки 3D','cells'),('Блоки','blocks'),('Высота, м','height'),('Осевые слои nz','nz'),
                          ('Минимальный якобиан','jacobian'),('Макс. отклонение углов, °','angle'),('Макс. пропорции 3D','aspect')):
            lines.append(f'{label:<30} {value(a[key]):>14} {value(b[key]):>14}')
        lines.append('A: '+('полная сетка' if a['complete'] else 'только слой')+'; B: '+('полная сетка' if b['complete'] else 'только слой'))
        if variant['geometry']!=self._comparison_geometry():lines.append('Геометрия/выбор подканалов различаются: серое наложение A скрыто, числа не означают улучшение одной задачи.')
        lines.append('Рисунок разрежен только для отображения. Экспорт использует B; A не восстанавливает актуальность B.')
        self.append_mesh_message('\n'.join(lines))

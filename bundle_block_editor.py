"""Batch editor helpers: patch changed fields, never copy an entire anchor block."""
from dataclasses import asdict,replace
from PySide6.QtCore import Qt,QSignalBlocker
from bundle_local_core import DEFAULTS

CORE_WIDGETS=dict(local_core_growth='core_growth',local_core_size='core_max_size',
                  local_core_limit='core_max_cells',local_core_layers='core_layers',
                  local_core_transition='core_transition')


def targets(panel):
    if panel.scope_mode!='block':return []
    ids=[]
    for item in panel.tree_blocks.selectedItems():
        data=item.data(0,Qt.UserRole)
        if data and data[0]=='block':ids.append(data[1])
    return sorted(set(ids)) or ([panel.combo_blocks.currentData()] if panel.combo_blocks.currentData() is not None else [])


def effective(panel,gid):
    w=panel.parent_window
    return w.block_custom_configs.get(gid,w.template_configs.get(w.get_template_for_block(gid),w.base_params))


def effective_core(panel,gid):
    w=panel.parent_window
    for p in (w.block_custom_configs.get(gid),w.template_configs.get(w.get_template_for_block(gid)),w.base_params):
        if p is not None and p.local_core_mode!='inherit':return {k:getattr(p,k) for k in DEFAULTS}
    return dict(getattr(panel,'_global_core_state',core_state(panel)))


def save(panel):
    p=panel.read_params();panel.sync_global_axial(p);w=panel.parent_window
    baseline=getattr(panel,'_display_params',p)
    changed={k:v for k,v in asdict(p).items() if v!=getattr(baseline,k)}
    from mesh_project import merge_project_inputs
    if panel.scope_mode=='all':w.base_params=merge_project_inputs(w.base_params,p)
    elif panel.scope_mode=='template':
        tid=panel.combo_templates.currentData()
        if tid is not None:w.template_configs[tid]=merge_project_inputs(w.template_configs.get(tid,w.base_params),p)
    else:
        for gid in targets(panel):
            old=effective(panel,gid)
            # For a single editor commit retain the same semantics; batch only
            # patches changed fields, preserving each block's other settings.
            value=replace(old,**changed) if len(targets(panel))>1 else merge_project_inputs(old,p)
            if changed or gid in w.block_custom_configs:w.block_custom_configs[gid]=value
    panel._display_params=p
    panel._loaded_params=w.base_params if panel.scope_mode=='all' else w.template_configs.get(panel.combo_templates.currentData(),w.base_params) if panel.scope_mode=='template' else effective(panel,targets(panel)[0]) if targets(panel) else p


def core_state(panel):
    mode=panel.combo_core_mode.currentData()
    active={'core_layers','core_transition'} if mode=='fixed_count' else {'core_growth','core_max_size','core_max_cells','core_transition'}
    data={}
    for k,v in CORE_WIDGETS.items():
        w=panel.fields[v];edit=w if hasattr(w,'model') else w.lineEdit()
        data[k]=w.model.raw if hasattr(w,'model') and (v not in active or edit.text()=='Разные значения') else w.value()
    data.update(local_core_mode=panel.combo_core_mode.currentData(),local_core_hermite=bool(panel.combo_core_lines.currentData()))
    return data


def save_core(panel):
    data=core_state(panel);w=panel.parent_window
    if panel.scope_mode!='all' and data==getattr(panel,'_display_core',data):return
    if panel.scope_mode=='all':panel._global_core_state=data
    elif panel.scope_mode=='template':
        tid=panel.combo_templates.currentData()
        if tid is not None:w.template_configs[tid]=replace(w.template_configs.get(tid,w.base_params),**data)
    else:
        previous=getattr(panel,'_display_core',data)
        patch={k:v for k,v in data.items() if v!=previous.get(k)}
        for gid in targets(panel):
            old=effective(panel,gid)
            inherited=asdict(old) if old.local_core_mode!='inherit' else effective_core(panel,gid)
            settings={k:inherited[k] for k in DEFAULTS};settings.update(patch)
            if patch:w.block_custom_configs[gid]=replace(old,**settings)
    panel._display_core=data
    if panel.scope_mode=='block' and targets(panel):panel._loaded_params=effective(panel,targets(panel)[0])
    elif panel.scope_mode=='template':panel._loaded_params=w.template_configs.get(panel.combo_templates.currentData(),w.base_params)
    if hasattr(panel,'_display_params'):
        panel._display_params=replace(panel._display_params,**{k:getattr(panel._loaded_params,k) for k in DEFAULTS})


def load_core(panel,p):
    if not hasattr(panel,'_global_core_state'):panel._global_core_state=core_state(panel)
    data=effective_core(panel,targets(panel)[0]) if panel.scope_mode=='block' and targets(panel) else panel._global_core_state if p.local_core_mode=='inherit' else {k:getattr(p,k) for k in DEFAULTS}
    before=panel.updating;panel.updating=True
    try:
        for k,v in CORE_WIDGETS.items():panel.fields[v].setValue(data[k])
        panel.combo_core_mode.setCurrentIndex(panel.combo_core_mode.findData(data['local_core_mode']))
        panel.combo_core_lines.setCurrentIndex(panel.combo_core_lines.findData(data['local_core_hermite']))
    finally:panel.updating=before
    panel._display_core=dict(data)


def selected(panel):
    if panel.updating:return
    ids=targets_for_tree(panel)
    if not ids:return
    blockers=[QSignalBlocker(panel.radio_block),QSignalBlocker(panel.radio_all),QSignalBlocker(panel.radio_template),QSignalBlocker(panel.combo_blocks)]
    panel.scope_mode='block';panel.radio_block.setChecked(True)
    panel.combo_blocks.setCurrentIndex(panel.combo_blocks.findData(ids[0]))
    del blockers
    panel.load_active_scope_to_ui()
    panel.parent_window.highlight_mesh_block(ids[0])


def targets_for_tree(panel):
    return sorted({item.data(0,Qt.UserRole)[1] for item in panel.tree_blocks.selectedItems()
                   if item.data(0,Qt.UserRole) and item.data(0,Qt.UserRole)[0]=='block'})


def mixed_description(panel):
    ids=targets(panel)
    if len(ids)<2:return ''
    values=[asdict(effective(panel,gid)) for gid in ids]
    names=dict(ni='ni',nj='число ячеек по нормали',h1='первый шаг',hmax='предельный шаг',law='закон',mode='способ задания',shape='параметр роста',wall_layers='слои призмы',layer_thickness='толщина слоя',layer_growth='рост слоя',local_core_mode='режим ядра',local_core_layers='слои ядра',local_core_transition='переход в ядро',local_core_growth='рост ядра',local_core_size='шаг ядра')
    mixed=[label for k,label in names.items() if any(v[k]!=values[0][k] for v in values[1:])]
    return f'Выбрано блоков: {len(ids)}. Меняются только отредактированные поля. '+('Разные значения: '+', '.join(mixed) if mixed else 'Значения одинаковы.')


def show_mixed_fields(panel):
    ids=targets(panel)
    fields={'ni':'ni','nj':'layers','h1':'h1','hmax':'hmax','wall_layers':'layer_cells',
            'layer_thickness':'layer_thickness','layer_growth':'layer_growth'}
    fields.update(CORE_WIDGETS)
    configs=[]
    for gid in ids:
        p=effective(panel,gid);data=asdict(p)
        data.update(effective_core(panel,gid))
        configs.append(data)
    mixed={widget for attr,widget in fields.items() if len(configs)>1 and any(p[attr]!=configs[0][attr] for p in configs[1:])}
    anchors=getattr(panel,'_mixed_anchors',{})
    for name in set(anchors)-mixed:
        w=panel.fields[name];edit=w if hasattr(w,'model') else w.lineEdit()
        if edit.text()=='Разные значения':w.setValue(anchors[name])
    panel._mixed_anchors={}
    for name in mixed:
        if name not in panel.fields:continue
        w=panel.fields[name]
        value=w.model.raw if hasattr(w,'model') else w.value()
        panel._mixed_anchors[name]=value
        edit=w if hasattr(w,'model') else w.lineEdit()
        with QSignalBlocker(w):
            if hasattr(w,'setMixed'):w.setMixed()
            else:edit.setText('Разные значения')

# Mixed text is a valid display state, not an invalid numeric draft. The stored
# anchor value remains available until the user enters a replacement.
from PySide6.QtWidgets import QSpinBox
from PySide6.QtGui import QValidator
from number_field import NumberField

class MixedSpinBox(QSpinBox):
    def __init__(self,*args):
        self._mixed=False
        super().__init__(*args)
        self.lineEdit().textEdited.connect(self._typed)
    def _typed(self,*args):self._mixed=False
    def textFromValue(self,value):
        return 'Разные значения' if self._mixed else super().textFromValue(value)
    def valueFromText(self,text):
        return self.value() if text=='Разные значения' else super().valueFromText(text)
    def validate(self,text,pos):
        if text=='Разные значения':return QValidator.Acceptable,text,pos
        return super().validate(text,pos)
    def setValue(self,value):
        self._mixed=False
        super().setValue(value)
    def setMixed(self):
        self._mixed=True
        self.lineEdit().setText('Разные значения')

class MixedNumberField(NumberField):
    def value(self):
        return self.model.raw if self.text()=='Разные значения' else super().value()
    def _finish(self):
        if self.text()!='Разные значения':super()._finish()

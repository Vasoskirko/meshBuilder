"""Surface tree sharing stable IDs with the preview and export assignments."""
from PySide6.QtCore import Qt,QItemSelectionModel
from PySide6.QtWidgets import QTreeWidget,QTreeWidgetItem,QAbstractItemView


def install_tree(d,layout):
    tree=QTreeWidget();tree.setHeaderLabels(['Поверхность','Назначение'])
    tree.setSelectionMode(QAbstractItemView.ExtendedSelection);tree.setMinimumWidth(210)
    tree.setToolTip('Одна поверхность — условие границы. Две поверхности (Ctrl) — интерфейс. Вход/выход также выбираются на схеме.')
    layout.addWidget(tree,1);d.surface_tree=tree;d._surface_tree_items={};busy=[False]
    def rebuild():
        busy[0]=True
        try:
            tree.clear();d._surface_tree_items={}
            catalog=d._surface_catalog
            for title,rows in (('Входы и выходы',catalog.get('endcaps',[])),('Стенки',catalog['rods']),('Боковые границы',catalog['sides'])):
                root=QTreeWidgetItem(tree,[title]);root.setFlags(root.flags()&~Qt.ItemIsSelectable)
                for row in rows:
                    if row.get('shared') and d.rb_inter_fuse.isChecked():continue
                    key=row['id'];description=''
                    if row.get('shared'):
                        combo=getattr(d,'_internal_combos',{}).get(row['pair_id'])
                        description='Wall · не соединять' if combo and combo.currentData()=='wall' else 'Internal · соседние подканалы'
                    for bc in d._conditions:
                        if bc['surface']==key:description=bc['kind']
                    for pair in d._pairs:
                        if key in (pair['first'],pair['second']):description=pair['kind']
                    item=QTreeWidgetItem(root,[key,description]);item.setData(0,Qt.UserRole,key)
                    d._surface_tree_items[key]=item
                root.setExpanded(True)
            tree.resizeColumnToContents(0)
        finally:busy[0]=False
    def selection():
        if busy[0] or d._compact_busy:return
        keys=[i.data(0,Qt.UserRole) for i in tree.selectedItems()]
        if len(keys)>2:d.surface_status.setText('Для интерфейса выберите ровно две поверхности.');return
        if not keys:
            d.surface_preview.highlight([]);d.preview_selection.setText('Выберите поверхность');return
        d.boundary_selection_mode.setCurrentIndex(1 if len(keys)==2 else 0)
        for combo,key in zip((d.surface_a,d.surface_b),keys):combo.setCurrentIndex(combo.findData(key))
        if len(keys)==1:
            existing=next((bc for bc in d._conditions if bc['surface']==keys[0]),None)
            if existing:
                d.surface_condition.setCurrentIndex(d.surface_condition.findData(existing['kind']));d.boundary_value.setValue(existing['value'])
        else:
            existing=next((p for p in d._pairs if set(keys)=={p['first'],p['second']}),None)
            if existing:
                for combo,key in zip((d.surface_a,d.surface_b),(existing['first'],existing['second'])):combo.setCurrentIndex(combo.findData(key))
                d.surface_condition.setCurrentIndex(d.surface_condition.findData(existing['kind']))
                if 'mass_flow' in existing:d.boundary_value.setValue(existing['mass_flow'])
        d.surface_preview.highlight(keys);d.preview_selection.setText(' ↔ '.join(keys))
        if len(keys)==1 and keys[0] in d._heat_fields:d.heat_table.selectRow(list(d._heat_fields).index(keys[0]))
    tree.itemSelectionChanged.connect(selection)
    def pick(key):
        item=d._surface_tree_items.get(key)
        if item is None:return
        tree.setCurrentItem(item,0,QItemSelectionModel.Toggle if getattr(d.surface_preview,'extend_selection',False) else QItemSelectionModel.ClearAndSelect);tree.scrollToItem(item)
    d.surface_preview.surfacePicked.connect(pick)
    d.rebuild_surface_tree=rebuild
    return tree

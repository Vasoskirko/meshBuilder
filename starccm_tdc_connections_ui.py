"""Readable connection overview; signed per-side editors remain available as details."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidgetItem,QHeaderView

KINDS=dict(fuse='Внутри Fuse',interface='Internal',periodic='Internal + Periodic',
           wall='Wall · адиабата',symmetry='Symmetry',mass_flow_inlet='Mass Flow Inlet',pressure_outlet='Pressure Outlet')


def fill_overview(d,paths,a,b,target):
    groups={}
    for p in paths:
        key=('closed',p['kind']) if p['default']=='zero' else ('connection',p['connection'])
        groups.setdefault(key,[]).append(p)
    rows=sorted(groups.values(),key=lambda ps:(ps[0]['connection']!=target,ps[0]['default']=='zero',ps[0]['connection']))
    table=d.tdc_connections
    current=table.item(table.currentRow(),0);selected=current.data(Qt.UserRole) if current else []
    table.setRowCount(len(rows))
    for i,ps in enumerate(rows):
        ps=sorted(ps,key=lambda p:(p["source"]!=a,p["source"]))
        p=ps[0];closed=p['default']=='zero';is_target=p['connection']==target
        title='Целевой зазор' if is_target else f'Закрытые стороны: {len(ps)} (не соединены)' if closed else 'Боковая периодическая пара' if p['kind']=='periodic' else 'Другой боковой обмен'
        roles=[];details=[]
        for side in ps:
            role='A' if side['source']==a else 'B'
            label=f'{role} · Подканал {side["source"]}'
            if label not in roles:roles.append(label)
            details.append(f'{label}: {side["id"]}')
        for side in ps:
            if side['neighbor'] and side['neighbor'] not in (a,b):
                label=f'сосед · Подканал {side["neighbor"]}'
                if label not in roles:roles.append(label)
        rule='Определяем из двух балансов A/B' if is_target else 'Нет переноса через эти стороны' if closed else 'Измеряем и вычитаем из баланса'
        if not closed and not is_target:
            modes=[d._tdc_methods.get(s['id'],s['default']) for s in ps]
            if 'unmeasured' in modes:rule='Нужно задать измерение → подробности'
            elif 'report' in modes:rule='Отчёты мощности → подробности'
            elif 'reconstruct' in modes:rule='Приближённая реконструкция → подробности'
        detail='\n'.join(details)+'\n'+rule
        if closed:detail+='\nОбъединены только для отображения: между ними нет интерфейса.'
        if not closed and not is_target:detail+='\nМощность каждой стороны учитывается в балансе своего подканала; две стороны не суммируются в один поток.'
        if is_target:detail+='\nОдин обмен, две стороны. Мощность проверяется по A и B независимо.'
        for j,text in enumerate((title,'; '.join(roles),KINDS[p['kind']],rule)):
            item=QTableWidgetItem(text);item.setFlags(item.flags()&~Qt.ItemIsEditable);item.setToolTip(detail)
            item.setData(Qt.UserRole,[s['id'] for s in ps]);table.setItem(i,j,item)
    table.resizeRowsToContents();table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    table.setFixedHeight(min(260,table.horizontalHeader().height()+sum(table.rowHeight(i) for i in range(len(rows)))+6))
    if rows:
        row=next((i for i in range(len(rows)) if table.item(i,0).data(Qt.UserRole)==selected),0)
        table.clearSelection();table.selectRow(row)

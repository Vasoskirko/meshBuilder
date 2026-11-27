"""Interactive cross-section preview backed by the export surface catalogue."""
from PySide6.QtCore import Signal,Qt
from PySide6.QtGui import QPainterPath,QPen,QBrush,QColor,QPainter,QPainterPathStroker
from PySide6.QtWidgets import QGraphicsView,QGraphicsScene,QGraphicsPathItem,QGraphicsItem


class SurfaceItem(QGraphicsPathItem):
    def __init__(self,path,key,view,pen):
        super().__init__(path);self.key=key;self.view=view;self.base_pen=pen;self.setPen(pen)
        self.setAcceptedMouseButtons(Qt.LeftButton);self.setToolTip(key)
    def shape(self):
        if self.brush().style()!=Qt.NoBrush:return self.path()
        # Cosmetic pens have screen-pixel width; the default item shape uses
        # scene units and can miss the painted curve after fitInView.
        scale=max(abs(self.view.transform().m11()),1e-12)
        stroke=QPainterPathStroker();stroke.setWidth(8./scale)
        stroke.setCapStyle(Qt.RoundCap);stroke.setJoinStyle(Qt.RoundJoin)
        return stroke.createStroke(self.path())
    def mousePressEvent(self,event):
        event.accept();self.view.extend_selection=bool(event.modifiers()&Qt.ControlModifier);self.view.surfacePicked.emit(self.key)


class SurfacePreview(QGraphicsView):
    surfacePicked=Signal(str)
    viewModeChanged=Signal(str)
    def __init__(self):
        super().__init__();self.setScene(QGraphicsScene(self));self.setMinimumSize(300,260)
        self.setRenderHint(QPainter.Antialiasing);self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.items_by_id={};self.view_mode='sides';self._catalog=None;self._fuse=False;self._drawing=False
    def set_view_mode(self,mode):
        if mode not in ('sides','Inlet','Outlet'):return
        if self.view_mode==mode:return
        self.view_mode=mode
        if self._catalog is not None:self.draw_catalog(self._catalog,self._fuse)
        self.viewModeChanged.emit(mode)
    def draw_catalog(self,catalog,fuse):
        self._catalog=catalog;self._fuse=fuse;self._drawing=True
        scene=self.scene();scene.clear();self.items_by_id={}
        base=self.palette().text().color();muted=self.palette().mid().color()
        for i,domain in enumerate(catalog['domains']):
            path=QPainterPath();points=domain['triangle'];path.moveTo(points[0][0]*1000,-points[0][1]*1000)
            for x,y in points[1:]:path.lineTo(x*1000,-y*1000)
            path.closeSubpath()
            for rod in domain.get('rods',[]):
                cx,cy=rod['center'];radius=rod['radius']*1000;solid=QPainterPath();solid.addEllipse(cx*1000-radius,-cy*1000-radius,2*radius,2*radius);path=path.subtracted(solid)
            color=self.palette().highlight().color() if fuse else QColor.fromHsv((i*57+205)%360,110,200)
            color.setAlpha(30);scene.addPath(path,QPen(muted,0),QBrush(color))
        for i,row in enumerate(catalog['rods'] if self.view_mode=='sides' else []):
            color=QColor.fromHsv((i*63+20)%360,180,190)
            self.add_surface(row,color,1.8)
        for row in catalog['sides'] if self.view_mode=='sides' else []:
            if fuse and row['shared']:
                for line in row['lines']:scene.addPath(self.path(line),QPen(muted,0,Qt.DashLine))
            else:self.add_surface(row,base,1.)
        bounds=scene.itemsBoundingRect();offset=0
        for role,index in (('Inlet',1),('Outlet',2)):
            if not catalog.get('endcaps') or self.view_mode!=role:continue
            for row in catalog.get('endcaps',[]):
                if row['role']!=role:continue
                path=QPainterPath()
                for domain in catalog['domains']:
                    if domain['number'] not in row['sources']:continue
                    points=domain['triangle'];part=QPainterPath();part.moveTo(points[0][0]*1000+offset*index,-points[0][1]*1000)
                    for x,y in points[1:]:part.lineTo(x*1000+offset*index,-y*1000)
                    part.closeSubpath()
                    for rod in domain.get('rods',[]):
                        cx,cy=rod['center'];radius=rod['radius']*1000;solid=QPainterPath();solid.addEllipse(cx*1000+offset*index-radius,-cy*1000-radius,2*radius,2*radius);part=part.subtracted(solid)
                    path=path.united(part)
                pen=QPen(base,1.);pen.setCosmetic(True);item=SurfaceItem(path,row['id'],self,pen);color=self.palette().highlight().color();color.setAlpha(45);item.setBrush(color);scene.addItem(item);self.items_by_id[row['id']]=[item]
        self.fitInView(scene.itemsBoundingRect().adjusted(-1,-1,1,1),Qt.KeepAspectRatio)
        self._drawing=False
    @staticmethod
    def path(line):
        path=QPainterPath();step=max(1,len(line)//250);points=line[::step]
        if points[-1]!=line[-1]:points=points+[line[-1]]
        path.moveTo(points[0][0]*1000,-points[0][1]*1000)
        for x,y in points[1:]:path.lineTo(x*1000,-y*1000)
        return path
    def add_surface(self,row,color,width):
        pen=QPen(color,width);pen.setCosmetic(True)
        for line in row['lines']:
            item=SurfaceItem(self.path(line),row['id'],self,pen);self.scene().addItem(item)
            self.items_by_id.setdefault(row['id'],[]).append(item)
    def highlight(self,key):
        keys={key} if isinstance(key,str) else set(key or [])
        cap=next((r for r in (self._catalog or {}).get('endcaps',[]) if r['id'] in keys),None)
        if not self._drawing and keys:
            self.set_view_mode(cap['role'] if cap else 'sides')
        self.scene().clearSelection()
        for name,items in self.items_by_id.items():
            for item in items:
                pen=QPen(item.base_pen)
                if name in keys:pen.setWidthF(4)
                item.setPen(pen)
    def resizeEvent(self,event):
        super().resizeEvent(event)
        if self.scene().items():self.fitInView(self.scene().itemsBoundingRect().adjusted(-1,-1,1,1),Qt.KeepAspectRatio)

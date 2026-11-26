"""Interactive cross-section preview backed by the export surface catalogue."""
from PySide6.QtCore import Signal,Qt
from PySide6.QtGui import QPainterPath,QPen,QBrush,QColor,QPainter
from PySide6.QtWidgets import QGraphicsView,QGraphicsScene,QGraphicsPathItem,QGraphicsItem


class SurfaceItem(QGraphicsPathItem):
    def __init__(self,path,key,view,pen):
        super().__init__(path);self.key=key;self.view=view;self.base_pen=pen;self.setPen(pen)
        self.setFlag(QGraphicsItem.ItemIsSelectable);self.setToolTip(key)
    def mousePressEvent(self,event):
        super().mousePressEvent(event);self.view.surfacePicked.emit(self.key)


class SurfacePreview(QGraphicsView):
    surfacePicked=Signal(str)
    def __init__(self):
        super().__init__();self.setScene(QGraphicsScene(self));self.setMinimumSize(300,260)
        self.setRenderHint(QPainter.Antialiasing);self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.items_by_id={}
    def draw_catalog(self,catalog,fuse):
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
        for i,row in enumerate(catalog['rods']):
            color=QColor.fromHsv((i*63+20)%360,180,190)
            self.add_surface(row,color,1.8)
        for row in catalog['sides']:
            if fuse and row['shared']:
                for line in row['lines']:scene.addPath(self.path(line),QPen(muted,0,Qt.DashLine))
            else:self.add_surface(row,base,1.)
        self.fitInView(scene.itemsBoundingRect().adjusted(-1,-1,1,1),Qt.KeepAspectRatio)
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
        self.scene().clearSelection()
        for name,items in self.items_by_id.items():
            for item in items:
                pen=QPen(item.base_pen)
                if name==key:pen.setWidthF(4);item.setSelected(True)
                item.setPen(pen)
    def resizeEvent(self,event):
        super().resizeEvent(event)
        if self.scene().items():self.fitInView(self.scene().itemsBoundingRect().adjusted(-1,-1,1,1),Qt.KeepAspectRatio)

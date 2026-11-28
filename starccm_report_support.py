"""Recorded STAR interface-side and local-frame helpers for diagnostics."""
REPORT_SUPPORT = r'''
    private InterfaceBoundary periodicReportSide(Region region,String base,String interfaceName) {
        InterfaceBoundary found=null;
        String prefix=base+" ["+interfaceName+" ";
        for(Boundary b:region.getBoundaryManager().getBoundaries())
            if(b instanceof InterfaceBoundary && (b.getPresentationName().startsWith(prefix) || b.getPresentationName().equals(base+" ["+interfaceName+"]"))) {
                if(found!=null)throw new IllegalStateException("Ambiguous interface side: "+prefix);
                found=(InterfaceBoundary)b;
            }
        if(found==null)throw new IllegalStateException("Interface side not found: "+prefix+"...]");
        return found;
    }
    private boolean reportNeedsMonitor(String name) {
        if(meshOnlyReport(name) || name.endsWith("_Area"))return false;
        if(name.matches(".*_(WallShearMean|Cf_Wall|DynamicPressure_In|Density_In|Density_Out|Viscosity_In|Viscosity_Out|Pressure_In|Pressure_Out|MassFlow_In|MassFlow_Out)$"))return false;
        if(name.matches("(MassFlow|Energy_Flow)_(Inlet|Outlet)_Total") || name.matches("TotalEnthalpy_(Inlet|Outlet)"))return false;
        return true;
    }
    private CartesianCoordinateSystem gapCoordinateSystem(Simulation sim,LabCoordinateSystem lab,Units metres,
            String name,double[] origin,double nx,double ny) {
        CartesianCoordinateSystem frame=findOwned(sim,lab.getLocalCoordinateSystemManager(),name,CartesianCoordinateSystem.class);
        if(frame==null) {
            frame=lab.getLocalCoordinateSystemManager().createLocalCoordinateSystem(CartesianCoordinateSystem.class,"Cartesian");
            frame.setPresentationName(name);own(sim,frame);
        }
        frame.getOrigin().setCoordinate(metres,metres,metres,new DoubleVector(origin));
        // Y is normal A -> B; X is tangential; X cross Y = global +Z.
        frame.getXVector().setComponents(ny,-nx,0.);
        frame.getXyPlane().setComponents(nx,ny,0.);
        return frame;
    }
'''

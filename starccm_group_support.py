"""Purpose-based nested groups for managed native STAR objects."""
GROUP_SUPPORT = r'''
    private String managedBucket(NamedObject object, String category) {
        String name=object.getPresentationName();
        if (category.equals("Parameters")) {
            if (name.equals("TimeStep")) return "Transient";
            if (Arrays.asList("rho","dynvis","kinvis","Cp","lambda","Pr").contains(name)) return "Properties";
            if (Arrays.asList("P_ref","T_ref").contains(name)) return "Reference";
            if (Arrays.asList("P_init","T_init","U_init").contains(name)) return "Initial";
            if (Arrays.asList("P_wet","S_in","D_hyd","ExportHeight","MB_ExportHeight").contains(name)) return "Geometry";
            if (Arrays.asList("y_plus_target","h1_wall").contains(name)) return "Grid_YPlus";
            return "FlowReference";
        }
        if (category.equals("FieldFunctions")) {
            if (name.startsWith("Bad") || Arrays.asList("CellQuality","FaceValidity","VolumeChange","SkewnessAngle").contains(name)) return "MeshQuality";
            if (Arrays.asList("One","X","Y","Z","ZFraction").contains(name)) return "Coordinates";
            if (name.contains("Mask")) return "SubchannelMasks";
            if (name.contains("Balance")) return "Balances";
            if (name.contains("WallShear")) return "Wall";
            return "Flow";
        }
        if (category.equals("Monitors")) {
            if (name.startsWith("TimeMean_") || name.startsWith("MB_TimeMean_")) return "MeanFields";
            try {
                Object report=object.getClass().getMethod("getReport").invoke(object);
                if (report instanceof NamedObject) name=((NamedObject)report).getPresentationName();
            } catch (Exception notReportMonitor) { /* Other native monitors keep their name. */ }
            if (meshOnlyReport(name)) return "LegacyStatic";
        }
        if (name.startsWith("Quality_")) return "MeshQuality";
        if (meshOnlyReport(name)) return "Geometry";
        if (name.contains("Imbalance") || name.contains("Balance") || name.startsWith("Energy_Flow_")) return "Balances";
        if (name.contains("Temperature") || name.contains("Heat") || name.contains("Enthalpy")) return "Thermal";
        if (name.contains("Shear") || name.contains("Cf_") || name.contains("Darcy")) return "Wall";
        if (name.startsWith("Gap_") || name.contains("_Gap_")) return "Gaps";
        if (name.startsWith("Subchannel_")) return "Subchannels";
        if (name.startsWith("Section_") || name.startsWith("Probe_") || name.contains("_Section_")) return "Sections";
        return "Flow";
    }
    private void nativeGroupObjects(Object manager, String name, List<NamedObject> members) throws Exception {
        for (java.lang.reflect.Method method : manager.getClass().getMethods()) {
            if (!method.getName().equals("groupObjects") || method.getParameterCount()!=3) continue;
            Class<?> expected=method.getParameterTypes()[1];
            Object collection=expected.isAssignableFrom(ArrayList.class) ? new ArrayList<>(members)
                : expected.isAssignableFrom(Vector.class) ? new Vector<>(members) : new NeoObjectVector(members.toArray());
            try { method.invoke(manager,name,collection,true); return; }
            catch (IllegalArgumentException mismatch) { /* Try compatible overload. */ }
        }
        throw new IllegalStateException("groupObjects API unavailable");
    }
    private Object managedRootGroup(Object manager, String name) throws Exception {
        Object group=null;
        try { group=manager.getClass().getMethod("getObject",String.class).invoke(manager,name); }
        catch (java.lang.reflect.InvocationTargetException notFound) { /* Create the missing folder. */ }
        if (group==null) {
            manager.getClass().getMethod("createGroup",String.class).invoke(manager,name);
            group=manager.getClass().getMethod("getObject",String.class).invoke(manager,name);
        }
        return group;
    }
    private void groupManaged(Simulation sim, Object manager, String category) {
        Map<String,List<NamedObject>> groups=new TreeMap<>();
        for (Object candidate : objects(manager)) {
            if (!(candidate instanceof NamedObject)) continue;
            NamedObject object=(NamedObject)candidate;
            if (!tagged(object,OWNER)) continue;
            groups.computeIfAbsent(managedBucket(object,category),k -> new ArrayList<>()).add(object);
        }
        if (groups.isEmpty()) return;
        try {
            Object roots=manager.getClass().getMethod("getGroupsManager").invoke(manager);
            // A nested group may only regroup members of its parent. Populate
            // the root first, then move its members into category subfolders.
            List<NamedObject> all=new ArrayList<>();
            for (List<NamedObject> members : groups.values()) all.addAll(members);
            nativeGroupObjects(roots,"meshBuilder_"+category,all);
            Object root=managedRootGroup(roots,"meshBuilder_"+category);
            Object folders=root.getClass().getMethod("getGroupsManager").invoke(root);
            for (Map.Entry<String,List<NamedObject>> entry : groups.entrySet()) {
                nativeGroupObjects(folders,entry.getKey(),entry.getValue());
                Object leaf=managedRootGroup(folders,entry.getKey());
                try {
                    Object actual=leaf.getClass().getMethod("getObjects").invoke(leaf);
                    if (actual instanceof Collection && !((Collection<?>)actual).containsAll(entry.getValue()))
                        throw new IllegalStateException("Folder "+entry.getKey()+" missing members; expected "+entry.getValue().size());
                } catch (NoSuchMethodException noMembershipAccessor) { /* Older API: native grouping succeeded. */ }
            }
        } catch (Exception e) { warn(sim,"  [!] Nested grouping " + category + ": " + e.getMessage()); }
    }
'''

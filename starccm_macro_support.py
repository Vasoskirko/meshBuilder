"""STAR Java helpers for ownership, repeatable updates and audit output."""
JAVA_SUPPORT = r'''
    private final List<String> issues = new ArrayList<>();
    private static final String OWNER = "meshBuilder.Managed";
    private String displayName(String name) { return name.startsWith("MB_") ? name.substring(3) : name; }
    private void warn(Simulation sim, String message) {
        issues.add(message); sim.println(message);
    }
    private Collection<?> objects(Object manager) {
        try { return (Collection<?>) manager.getClass().getMethod("getObjects").invoke(manager); }
        catch (Exception e) { throw new IllegalStateException("Cannot enumerate " + manager.getClass().getName(), e); }
    }
    private List<Tag> tags(NamedObject object) {
        try {
            Object group = object.getClass().getMethod("getTagGroup").invoke(object);
            Collection<?> current = (Collection<?>) group.getClass().getMethod("getObjects").invoke(group);
            List<Tag> result = new ArrayList<>();
            for (Object tag : current) result.add((Tag) tag);
            return result;
        } catch (Exception e) { throw new IllegalStateException("Cannot inspect ownership of " + object.getPresentationName(), e); }
    }
    private Tag tag(Simulation sim, String name) {
        for (Tag current : sim.get(TagManager.class).getObjects())
            if (current.getPresentationName().equals(name)) return current;
        return sim.get(TagManager.class).createNewUserTag(name);
    }
    private boolean tagged(NamedObject object, String name) {
        for (Tag t : tags(object)) if (t.getPresentationName().equals(name)) return true;
        return false;
    }
    private void mark(Simulation sim, NamedObject object, String label) {
        List<Tag> current = tags(object);
        Tag t = tag(sim, label);
        if (!current.contains(t)) current.add(t);
        sim.get(TagManager.class).setTags(object, current);
    }
    private void own(Simulation sim, NamedObject object) { mark(sim, object, OWNER); object.setPresentationName(displayName(object.getPresentationName())); }
    private <T extends NamedObject> T findOwned(Simulation sim, Object manager, String name, Class<T> type) {
        T found=null;
        for (Object candidate : objects(manager)) {
            if (!(candidate instanceof NamedObject)) continue;
            NamedObject object = (NamedObject) candidate;
            String actual=object.getPresentationName();
            if (!name.equals(actual) && !(name.startsWith("MB_") && displayName(name).equals(displayName(actual)))) continue;
            if (!tagged(object, OWNER)) throw new IllegalStateException("Name belongs to a user object: " + actual);
            if (!type.isInstance(object)) throw new IllegalStateException("Incompatible object type: " + actual);
            if (found!=null) throw new IllegalStateException("Ambiguous managed name: " + name);
            found=type.cast(object);
        }
        if (found!=null && name.startsWith("MB_")) found.setPresentationName(displayName(name));
        return found;
    }
    private <T extends Report> T ownedReport(Simulation sim, String name, Class<T> type) {
        T report = findOwned(sim, sim.getReportManager(), name, type);
        if (report == null) {
            report = sim.getReportManager().createReport(type);
            report.setPresentationName(name); own(sim, report);
        }
        return report;
    }
    private ThresholdPart threshold(Simulation sim, List<? extends NamedObject> input, FieldFunction ff, String name) {
        ThresholdPart part = findOwned(sim, sim.getPartManager(), name, ThresholdPart.class);
        if (part == null) {
            part = sim.getPartManager().createThresholdPart(new NeoObjectVector(input.toArray()),
                    new DoubleVector(new double[] {0.5,1.5}), sim.getUnitsManager().getObject(""), ff, 0);
            part.setPresentationName(name); own(sim, part);
        }
        part.getInputParts().setObjects(input); part.setFieldFunction(ff);
        part.setMode(ThresholdMode.BETWEEN_TAG);
        part.setRange(new DoubleVector(new double[] {0.5,1.5}));
        return part;
    }
    private List<Region> preparedRegions(Simulation sim, String fingerprint, int expected) {
        List<Region> result = new ArrayList<>();
        for (Region region : sim.getRegionManager().getRegions()) {
            for (Tag t : tags(region)) {
                if (t.getPresentationName().startsWith("meshBuilder.Mesh.")
                        && !t.getPresentationName().equals("meshBuilder.Mesh." + fingerprint))
                    throw new IllegalStateException("Mesh/topology differs from this export. Use a new simulation.");
            }
            if (tagged(region, "meshBuilder.Mesh." + fingerprint)) result.add(region);
        }
        if (!result.isEmpty()) {
            if (result.size()!=expected) throw new IllegalStateException("Managed region count changed; use a new simulation.");
            result.sort(Comparator.comparingInt(r -> {
                for (Tag t : tags(r)) if (t.getPresentationName().startsWith("meshBuilder.Source."))
                    return Integer.parseInt(t.getPresentationName().substring("meshBuilder.Source.".length()));
                throw new IllegalStateException("Source region tag missing");
            }));
        }
        return result;
    }
    private void markBoundaryRoles(Simulation sim, List<Boundary> inlets, List<Boundary> outlets, List<Boundary> rods, List<Boundary> gaps) {
        for (Boundary b : inlets) mark(sim,b,"meshBuilder.Role.Inlet");
        for (Boundary b : outlets) mark(sim,b,"meshBuilder.Role.Outlet");
        for (Boundary b : rods) mark(sim,b,"meshBuilder.Role.Rod");
        for (Boundary b : gaps) mark(sim,b,"meshBuilder.Role.Gap");
    }
    private ElementCountReport countReport(Simulation sim, String name, List<? extends NamedObject> parts, int[] counts) {
        ElementCountReport report = ownedReport(sim,name,ElementCountReport.class);
        report.getParts().setObjects(parts); registerReport(sim,report,counts); return report;
    }
    private UserFieldFunction createBadCells(Simulation sim, List<Region> regions, FieldFunction metric, String key,
            String condition, int[] counts) {
        try {
            String expression = "(${" + metric.getFunctionName() + "} " + condition + ") ? 1.0 : 0.0";
            UserFieldFunction mask = getOrCreateFF(sim,"MB_Bad_" + key,expression);
            mask.setDimensions(Dimensions.Builder().build());
            ThresholdPart bad = threshold(sim,regions,mask,"Quality_BadCells_" + key);
            countReport(sim,"Quality_BadCount_" + key,Collections.singletonList(bad),counts);
            createExpressionReport(sim,"Quality_BadPercent_" + key,
                    "100 * ${Quality_BadCount_" + key + "Report} / max(${Quality_TotalCellCountReport},1)",counts);
            return mask;
        } catch (Exception e) { warn(sim,"  [!] Bad cells " + key + ": " + e.getMessage()); return null; }
    }
    private void badUnion(Simulation sim,List<Region> regions,List<UserFieldFunction> masks,int[] counts) {
        if (masks.size()!=4) { warn(sim,"  [!] Combined bad-cell mask unavailable: one or more criteria failed");return; }
        try {
            List<String> tests=new ArrayList<>();
            for (UserFieldFunction mask : masks) tests.add("${" + mask.getFunctionName() + "} > 0.5");
            UserFieldFunction mask=getOrCreateFF(sim,"MB_BadAnyQuality","("+String.join(" || ",tests)+") ? 1.0 : 0.0");
            mask.setDimensions(Dimensions.Builder().build());
            ThresholdPart part=threshold(sim,regions,mask,"Quality_BadCells_Any");
            countReport(sim,"Quality_BadCount_Any",Collections.singletonList(part),counts);
            createExpressionReport(sim,"Quality_BadPercent_Any","100 * ${Quality_BadCount_AnyReport} / max(${Quality_TotalCellCountReport},1)",counts);
        } catch (Exception e) { warn(sim,"  [!] Combined bad cells: "+e.getMessage()); }
    }
    private void supportFunctions(Simulation sim, double height, List<String> selected) {
        if (selected.contains("z_fraction")) try {
            // A dimensioned global parameter is valid STAR syntax; inline [m] literals are not.
            exportHeight(sim,height);
            getOrCreateFF(sim,"MB_Z","$$Centroid[2]").setDimensions(Dimensions.Builder().length(1).build());
            UserFieldFunction ff=getOrCreateFF(sim,"MB_ZFraction","${MB_Z} / ${ExportHeight}");
            ff.setDimensions(Dimensions.Builder().build());
        } catch (Exception e) { warn(sim,"  [!] Relative height: " + e.getMessage()); }
        if (selected.contains("speed")) try {
            UserFieldFunction ff=getOrCreateFF(sim,"MB_Speed","mag($$Velocity)");
            ff.setDimensions(Dimensions.Builder().length(1).time(-1).build());
        } catch (Exception e) { warn(sim,"  [!] Speed: " + e.getMessage()); }
        if (selected.contains("mass_flux")) try {
            UserFieldFunction ff=getOrCreateFF(sim,"MB_MassFluxMagnitude","${Density} * mag($$Velocity)");
            ff.setDimensions(Dimensions.Builder().mass(1).length(-2).time(-1).build());
        } catch (Exception e) { warn(sim,"  [!] Mass flux: " + e.getMessage()); }
    }
    private void groupManaged(Simulation sim, Object manager, String category) {
        Map<String,List<NamedObject>> groups=new TreeMap<>();
        for (Object candidate : objects(manager)) {
            if (!(candidate instanceof NamedObject)) continue;
            NamedObject object=(NamedObject)candidate;
            if (!tagged(object,OWNER)) continue;
            String name=object.getPresentationName();
            String detail = name.startsWith("Quality_") || name.startsWith("Bad_") ? "Quality"
                : name.startsWith("Gap_") || name.startsWith("MassFlow_Gap_") ? "Gaps"
                : name.startsWith("Subchannel_") ? "Subchannels"
                : name.startsWith("Section_") || name.startsWith("Probe_") ? "Sections"
                : category;
            groups.computeIfAbsent("meshBuilder_"+detail,k -> new ArrayList<>()).add(object);
        }
        for (Map.Entry<String,List<NamedObject>> entry : groups.entrySet()) {
            try {
                Object managerGroups=manager.getClass().getMethod("getGroupsManager").invoke(manager);
                boolean success=false;
                for (java.lang.reflect.Method method : managerGroups.getClass().getMethods()) {
                    if (!method.getName().equals("groupObjects") || method.getParameterCount()!=3) continue;
                    Object collection=method.getParameterTypes()[1].isAssignableFrom(ArrayList.class)
                        ? new ArrayList<>(entry.getValue()) : new NeoObjectVector(entry.getValue().toArray());
                    try { method.invoke(managerGroups,entry.getKey(),collection,true); success=true;break; }
                    catch (IllegalArgumentException mismatch) { /* Try another supported overload. */ }
                }
                if (!success) throw new IllegalStateException("groupObjects API unavailable");
            } catch (Exception e) { warn(sim,"  [!] Group " + entry.getKey() + ": " + e.getMessage()); }
        }
    }
    private String csv(String value) { return "\"" + value.replace("\"","\"\"") + "\""; }
    private void writeSummary(Simulation sim, List<Region> regions, String fingerprint, long expectedCells) {
        List<String[]> rows=new ArrayList<>();
        rows.add(new String[]{"export","signature",fingerprint,"","info"});
        rows.add(new String[]{"export","settings",exportSettings,"JSON","requested"});
        try { rows.add(new String[]{"export","star_version",sim.getStarVersion().getString("ReleaseNumber"),"","info"}); }
        catch (Exception e) { warn(sim,"  [!] STAR version unavailable: "+e.getMessage()); }
        rows.add(new String[]{"mesh","expected_cells",Long.toString(expectedCells),"cells","info"});
        rows.add(new String[]{"mesh","regions",Integer.toString(regions.size()),"","info"});
        sim.println("=== meshBuilder audit: expected " + expectedCells + " cells, " + regions.size() + " regions ===");
        boolean initialized=sim.getSolution().isInitialized();
        for (Report report : sim.getReportManager().getObjects()) if (tagged(report,OWNER)) {
            if (!initialized && !meshOnlyReport(report.getPresentationName())) {
                rows.add(new String[]{"report",report.getPresentationName(),"","","deferred: solution not initialized"});
                sim.println("Deferred until initialization: " + report.getPresentationName());
                continue;
            }
            try {
                double value=report.getReportMonitorValue();
                if (!Double.isFinite(value)) throw new IllegalStateException("Nonfinite report value");
                rows.add(new String[]{"report",report.getPresentationName(),Double.toString(value),report.getUnits()==null?"":report.getUnits().getPresentationName(),"evaluated"});
                sim.println(report.getPresentationName()+" = "+value);
                if (report.getPresentationName().equals("Quality_TotalCellCount") && Math.abs(value-expectedCells)>.5)
                    warn(sim,"  [!] Imported cell count differs from the exported mesh");
            } catch (Exception e) { warn(sim,"  [!] Audit report " + report.getPresentationName() + ": " + e.getMessage()); }
        }
        Object[] managers={sim.getPartManager(),sim.getReportManager(),sim.getMonitorManager(),
            sim.getPlotManager(),sim.getSceneManager(),sim.getFieldFunctionManager()};
        String[] categories={"parts","reports","monitors","plots","scenes","field_functions"};
        for (int i=0;i<managers.length;i++) {
            int count=0;
            for (Object candidate : objects(managers[i])) if (candidate instanceof NamedObject && tagged((NamedObject)candidate,OWNER)) count++;
            rows.add(new String[]{"objects",categories[i],Integer.toString(count),"objects","managed"});
            sim.println("Managed "+categories[i]+": "+count);
        }
        for (String issue : issues) rows.add(new String[]{"issue","warning",issue,"","check"});
        try {
            java.nio.file.Path output=java.nio.file.Files.createTempFile(java.nio.file.Paths.get(resolvePath(".")),"meshBuilder_audit_",".csv");
            try (java.io.BufferedWriter writer=java.nio.file.Files.newBufferedWriter(output,java.nio.charset.StandardCharsets.UTF_8)) {
                writer.write("category,name,value,units,status\n");
                for (String[] row : rows) {
                    for (int i=0;i<row.length;i++) { if (i>0)writer.write(",");writer.write(csv(row[i])); }
                    writer.write("\n");
                }
            }
            sim.println("Audit CSV: "+output);
        } catch (Exception e) { warn(sim,"  [!] Audit CSV: "+e.getMessage()); }
        sim.println("Audit warnings: "+issues.size()+". Inspect boundary conditions and initialize/evaluate diagnostics before accepting results.");
    }
    private void cleanManagedDisplayNames(Simulation sim) {
        Object[] managers={sim.getFieldFunctionManager(),sim.getMonitorManager()};
        for (Object manager : managers) for (Object candidate : objects(manager)) {
            if (!(candidate instanceof NamedObject)) continue;
            NamedObject object=(NamedObject)candidate;
            String name=object.getPresentationName();
            if (!name.startsWith("MB_") || !tagged(object,OWNER)) continue;
            try { findOwned(sim,manager,name,NamedObject.class); }
            catch (Exception e) { warn(sim,"  [!] Display name " + name + ": " + e.getMessage()); }
        }
    }
'''

"""Keep signed molecular transport distinct from total advection and mean convection."""
import os,subprocess,tempfile,unittest
from pathlib import Path
os.environ['QT_QPA_PLATFORM']='offscreen'
import test_compact_star_export as fixture
from test_unified_tdc import enable_tdc
from starccm_tdc_plan import build_plan
from starccm_tdc_export import render_controller,replace_method
from starccm_tdc_components import KEYS


class ComponentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.CompactExportTests.setUpClass();cls.app=fixture.CompactExportTests.app;cls.mesh=fixture.CompactExportTests.mesh;cls.model=fixture.CompactExportTests.model
    dialog=fixture.CompactExportTests.dialog
    def code(self,d):
        v=d.read_options();return render_controller(build_plan(d.mesh_result,d.bundle_model,v,d.read_fluid(),d.yplus_data),v)
    def test_components_use_target_gradient_and_constant_lambda_not_effective_conductivity(self):
        d=enable_tdc(self.dialog());code=self.code(d)
        self.assertIn('surface("Target_A_Molecular"',code);self.assertIn('surface("Target_B_Molecular"',code)
        self.assertIn('ff("Target_A_MolecularFlux","-"+ref("Lambda")',code)
        self.assertIn('grad(${Temperature})',code);self.assertNotIn('EffectiveConductivity',code)
        self.assertIn('energy.getFunctionName()',code);self.assertNotIn('TDC_Turbulent',code)
        # The extra measurements are mandatory sampled reports, never merely unused FFs.
        self.assertIn('dim(1,0,-3,0)),true)',code)
        for k in KEYS:self.assertIn('"'+k+'"',code)
        v=d.read_options();other=self.dialog();other.apply_options(v);self.assertEqual(other.read_options(),v)
        d.tdc_components.setChecked(False);code=self.code(d)
        self.assertNotIn('Target_A_Molecular',code);self.assertNotIn('Target_Molecular_A_W',code)
        other.apply_options(d.read_options());self.assertFalse(other.tdc_components.isChecked())
    def test_actual_java_derived_fields_preserve_signs_and_do_not_call_advection_turbulence(self):
        import test_tmc_hybrid as jt
        cmd,java=jt.compiler()
        if cmd is None:self.skipTest('JDK unavailable; not Siemens SDK')
        d=enable_tdc(self.dialog());code=self.code(d)
        def method(name):
            marker='UNIQUE';changed=replace_method(code,name,marker);start=changed.index(marker);suffix=changed[start+len(marker):]
            return code[start:len(code)-len(suffix)]
        kernel=code[code.index('    static final class WeightedWindow'):code.rfind('}')]
        harness='''import java.util.*;
class Check {
 static final String P="TDC_";
 double value(String k){return k.equals("Cp")?2:k.equals("MinDeltaT")?.01:.05;}
 HELPERS
 KERNEL
 public static void main(String[] args){
  Check c=new Check();List<String> names=new ArrayList<>();for(String k:new String[]{"A_Exchange_NoStorage","B_Exchange_NoStorage","A_SensibleEnergy","B_SensibleEnergy","DeltaT_BulkLength","MassFluxRef","A_OtherOut","B_OtherOut","Target_A_Advective","Target_B_Advective","Target_A_Molecular","Target_B_Molecular"})names.add(P+k);
  WeightedWindow w=new WeightedWindow(names);
  w.add(0,new double[]{12,-11,0,2,2,5,0,0,6,-6,1,-1});w.add(2,new double[]{12,-11,4,0,2,5,0,0,8,-8,3,-3});
  Map<String,Double> r=c.derived(w);
  if(r.get("Exchange_A_W")!=10 || r.get("Target_Advective_A_W")!=7 || r.get("Target_Molecular_A_W")!=2 || r.get("Target_Molecular_B_W")!=2 || r.get("Target_NonMolecular_A_W")!=8 || r.get("Target_NonMolecular_B_W")!=8 || r.get("Target_MolecularPairMismatch_W")!=0 || r.get("Target_BalanceRemainder_A_W")!=1 || r.get("Target_BalanceRemainder_B_W")!=1)throw new AssertionError(r);
  for(String k:r.keySet())if(k.contains("Turbulent"))throw new AssertionError("Unmeasured mean convection cannot be zero");
  WeightedWindow reverse=new WeightedWindow(names);
  reverse.add(0,new double[]{-12,11,4,0,-2,5,0,0,-6,6,-1,1});reverse.add(2,new double[]{-12,11,0,2,-2,5,0,0,-8,8,-3,3});
  Map<String,Double> b=c.derived(reverse);if(b.get("Target_Molecular_A_W")!=-2 || b.get("Target_NonMolecular_A_W")!=-8 || b.get("ResultValid")!=1 || Math.abs(b.get("TDC_Effective")-r.get("TDC_Effective"))>1e-12)throw new AssertionError(b);
 }}'''.replace('HELPERS',method('derived')+'\n'+method('derivedKeys')).replace('KERNEL',kernel)
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'Check.java';path.write_text(harness)
            r=subprocess.run([java,str(path)],capture_output=True,text=True,timeout=60)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)

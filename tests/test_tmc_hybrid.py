"""STAR SDK is unavailable: test Java syntax against contracts, execute numerical kernel."""
from pathlib import Path
import os,shutil,subprocess,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(Path(__file__).parent/'tmc'))
from java_stubs import write_stubs
SOURCE=ROOT/'tmc'/'TMC_Hybrid.java'


def compiler():
    javac=shutil.which('javac');java=os.environ.get('TMC_JAVA') or shutil.which('java')
    if javac and java:return [javac,'-encoding','UTF-8','-d'],java
    if java and 'jdk.compiler' in subprocess.run([java,'--list-modules'],capture_output=True,text=True).stdout:
        return [java,'-m','jdk.compiler/com.sun.tools.javac.Main','-encoding','UTF-8','-d'],java
    ecj=os.environ.get('TMC_ECJ_JAR')
    if java and ecj:return [java,'-jar',ecj,'-17','-encoding','UTF-8','-d'],java
    return None,None


class TmcJavaTests(unittest.TestCase):
    def test_macro_compiles_with_explicit_api_contracts_and_kernel_executes(self):
        command,java=compiler()
        if command is None:self.skipTest('Java compiler unavailable; this is not a STAR SDK compile')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);write_stubs(root)
            package=root/'macro';package.mkdir();shutil.copy(SOURCE,package/SOURCE.name)
            (package/'TmcKernelTest.java').write_text(r'''
package macro;
import java.util.*;
public class TmcKernelTest {
 static void close(double a,double b){if(Math.abs(a-b)>1e-11)throw new AssertionError(a+" != "+b);}
 static void reject(Runnable r){try{r.run();}catch(IllegalArgumentException|IllegalStateException expected){return;}throw new AssertionError("accepted invalid input");}
 public static void main(String[] args){
  TMC_Hybrid.WeightedWindow w=new TMC_Hybrid.WeightedWindow(Arrays.asList("TMC_x"));
  w.add(0,new double[]{0});w.add(1,new double[]{2});w.add(3,new double[]{2});
  close(w.mean("x"),5./3);close(w.duration(),3);close(w.sd(0),Math.sqrt(5./9));
  close(w.first("x"),0);close(w.last("x"),2);
  reject(()->w.add(3,new double[]{2}));reject(()->w.add(4,new double[]{Double.NaN}));
  reject(()->w.add(4,new double[]{1,2}));
  TMC_Hybrid.WeightedWindow empty=new TMC_Hybrid.WeightedWindow(Arrays.asList("x"));reject(()->empty.duration());
  TMC_Hybrid.WeightedWindow products=new TMC_Hybrid.WeightedWindow(Arrays.asList("m","h","mh"));
  products.add(0,new double[]{1,3,3});products.add(2,new double[]{3,1,3});
  close(products.mean(2),3);close(products.mean(0)*products.mean(1),4);
  double expected=621.796/(3*.00254*.3*5225.098*2534.3*4);
  close(TMC_Hybrid.tmcCoefficient(621.796,3,.00254*.3,5225.098,2534.3,4,.01),expected);
  reject(()->TMC_Hybrid.tmcCoefficient(1,3,1,1,1,0,.01));
  reject(()->TMC_Hybrid.tmcCoefficient(-1,3,1,1,1,1,.01));
  reject(()->TMC_Hybrid.tmcCoefficient(1,3,1,1,1,.001,.01));
  System.out.println("Java numerical checks passed");
 }
}
''')
            classes=root/'classes';classes.mkdir()
            result=subprocess.run(command+[str(classes)]+[str(p) for p in root.rglob('*.java')],capture_output=True,text=True,timeout=90)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            result=subprocess.run([java,'-cp',str(classes),'macro.TmcKernelTest'],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('checks passed',result.stdout)

    def test_reference_and_non_destructive_controls_are_documented_in_source(self):
        source=SOURCE.read_text()
        self.assertIn('getFullyDevelopedMassFlowRate().setDefinition(ref("MassFlow"))',source)
        self.assertIn('setDefinition(rr("qvSource"))',source)
        self.assertIn('rr("WallHeatSigned_All")+" / "+rr("Volume_All")',source)
        self.assertNotIn('initializeSolution(',source)
        self.assertNotIn('MaximumReport',source)
        self.assertIn('MaxReport.class',source)
        self.assertIn('ensureContinuation(directory)',source)
        self.assertIn('Native field-mean pause API not available',source)
        self.assertIn('TMC_Effective includes molecular/mean-flow contributions',source)

if __name__=='__main__':unittest.main()

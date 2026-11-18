from pathlib import Path
import sys, unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fluid_properties import water_iapws97, _saturation_pressure_mpa

class WaterRegionTests(unittest.TestCase):
    def test_if97_region1_reference_points(self):
        # IF97 Region 1 verification values: specific volume and cp in SI.
        for T,p,v,cp in [(300,3,.00100215168,4173.01218),
                          (300,80,.000971180894,4010.08987),
                          (500,3,.001202418,4655.80682)]:
            with self.subTest(T=T,p=p):
                r=water_iapws97(T-273.15,p)
                self.assertAlmostEqual(r['density'],1/v,delta=.02)
                self.assertAlmostEqual(r['cp'],cp,delta=.1)
    def test_region4_reference_and_liquid_boundary(self):
        self.assertAlmostEqual(_saturation_pressure_mpa(300),.00353658941,places=10)
        for T in (273.15,373.15,573.15,623.15):
            ps=_saturation_pressure_mpa(T)
            self.assertGreater(water_iapws97(T-273.15,ps)['density'],0)
            with self.assertRaises(ValueError):water_iapws97(T-273.15,ps*.99)
    def test_invalid_inputs(self):
        for T,p in [(300,.1),(25,101),(25,0),(-1,1),(351,20),
                    (float('nan'),1),(25,float('nan')),(25,float('inf'))]:
            with self.subTest(T=T,p=p), self.assertRaises(ValueError):water_iapws97(T,p)

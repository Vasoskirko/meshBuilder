import csv
import tempfile
import unittest
from pathlib import Path
from tmc.analyse_series import analyse,read_block

class TmcSeriesTests(unittest.TestCase):
    def fixture(self,path):
        (path/'configuration.txt').write_text('Cp=4\nLength=2\nGapWidth=0.5\nEquivalentGapCount=3\n')
        header=['time_s','TMC_Sub1_SensibleEnergy','TMC_Sub2_SensibleEnergy',
                'TMC_Sub1_Exchange_NoStorage','TMC_Sub2_Exchange_NoStorage',
                'TMC_DeltaT_BulkLength','TMC_MassFluxRef','TMC_EnergyResidual_NoStorage']
        # Storage 2 W in each subchannel; corrected exchange +12 W from hot and -12 W from cold.
        rows=[[0,0,0,-10,14,1,2,4],[1,2,2,-10,14,3,2,4],[3,6,6,-10,14,3,2,4]]
        self.write(path/'block_00001.csv',header,rows[:2]);self.write(path/'block_00002.csv',header,rows[1:])
        return header,rows
    def write(self,path,header,rows):
        with path.open('w',newline='') as stream:
            writer=csv.writer(stream);writer.writerow(header);writer.writerows(rows)
    def test_variable_dt_weighted_ratio_and_storage(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);self.fixture(path);result=analyse(path)
        self.assertAlmostEqual(result['means']['TMC_DeltaT_BulkLength'],8/3)
        self.assertAlmostEqual(result['exchange_hot_W'],12);self.assertAlmostEqual(result['exchange_cold_W'],12)
        self.assertAlmostEqual(result['thermal_residual_with_storage_W'],0)
        self.assertAlmostEqual(result['TMC_effective'],12/(3*.5*2*4*2*(8/3)))
        self.assertNotEqual(result['TMC_effective'],sum(b['TMC_effective'] for b in result['blocks'])/2)
    def test_rejects_gap_and_changed_shared_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);header,rows=self.fixture(path)
            self.write(path/'block_00002.csv',header,[[2,*rows[1][1:]],rows[2]])
            with self.assertRaisesRegex(ValueError,'Gap/overlap'):analyse(path)
            changed=[list(r) for r in rows[1:]];changed[0][5]=9
            self.write(path/'block_00002.csv',header,changed)
            with self.assertRaisesRegex(ValueError,'Discontinuous'):analyse(path)
    def test_partial_nonfinite_and_repeated_time_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);header,rows=self.fixture(path)
            (path/'block_00003.partial.csv').write_text('incomplete')
            self.assertEqual(len(analyse(path)['blocks']),2)
            for bad in ([rows[0],rows[0]],[[0,0],[1,2]],[[*rows[0]],[3,0,0,-10,14,float('nan'),2,4]]):
                self.write(path/'invalid.csv',header,bad)
                with self.assertRaises(ValueError):read_block(path/'invalid.csv')

if __name__=='__main__':unittest.main()

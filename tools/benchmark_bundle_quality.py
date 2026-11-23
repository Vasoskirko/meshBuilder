"""Measure quality stage only; optional reference is an exported mesh_quality.py."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from bundle_geometry import BundleModel
from mesh_core import MeshParams
from mesh_subchannel import build_mesh_from_bundle_model
from bundle_mesh_jobs import analyse_subchannel_result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ni',type=int,default=40)
    parser.add_argument('--nj',type=int,default=50)
    parser.add_argument('--nz',type=int,default=12)
    parser.add_argument('--reference',type=Path)
    parser.add_argument('--report',type=Path)
    args=parser.parse_args()
    model=BundleModel()
    model.selected_subchannels={i for i,s in model.subchannels.items() if s.sub_type=='interior'}
    result=build_mesh_from_bundle_model(model,MeshParams(ni=args.ni,nj=args.nj,nz=args.nz))
    reference=None
    if args.reference:
        spec=importlib.util.spec_from_file_location('reference_quality',args.reference)
        reference=importlib.util.module_from_spec(spec)
        sys.modules[spec.name]=reference
        spec.loader.exec_module(reference)
    start=time.perf_counter()
    if reference is None:
        report=analyse_subchannel_result(result,lambda *args:None)
    else:
        blocks=reference.extrude_blocks(result.blocks,np.linspace(0,result.params.z_len,result.params.nz+1))
        interfaces=[(i.block_a,i.face_a,i.block_b,i.face_b,i.reversed) for i in result.interfaces]
        report=reference.analyse_blocks(blocks,interfaces=interfaces)
    print(f'Cells: {report["totals"]["cells"]:,}; quality: {time.perf_counter()-start:.3f} s')
    try:
        import resource
        peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        mib=peak/(1024**2 if sys.platform=='darwin' else 1024)
        print(f'Whole-process peak RSS: {mib:.2f} MiB')
    except ImportError:
        print('Peak RSS unavailable on this platform')
    if args.report:
        args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()

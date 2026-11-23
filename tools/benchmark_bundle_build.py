"""Repeatable generator benchmark; excludes quality, drawing and export."""
import argparse
from pathlib import Path
import statistics
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bundle_geometry import BundleModel
from mesh_core import MeshParams
from mesh_subchannel import build_mesh_from_bundle_model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ni', type=int, default=80)
    parser.add_argument('--nj', type=int, default=100)
    parser.add_argument('--nz', type=int, default=20)
    parser.add_argument('--repeat', type=int, default=3)
    args = parser.parse_args()
    if min(args.ni, args.nj) < 2 or min(args.nz, args.repeat) < 1:
        parser.error('ni/nj >= 2, nz/repeat >= 1 required')
    model = BundleModel()
    model.selected_subchannels = {i for i, s in model.subchannels.items() if s.sub_type == 'interior'}
    params = MeshParams(ni=args.ni, nj=args.nj, nz=args.nz)
    elapsed = []
    for _ in range(args.repeat):
        start = time.perf_counter()
        result = build_mesh_from_bundle_model(model, params)
        elapsed.append(time.perf_counter()-start)
    print(f'Blocks: {len(result.blocks)}, equivalent 3D cells: {result.diagnostics["cells_3d"]:,}')
    print('Generator seconds:', ', '.join(f'{v:.3f}' for v in elapsed))
    print(f'Median: {statistics.median(elapsed):.3f} s; quality/drawing/export excluded')


if __name__ == '__main__':
    main()

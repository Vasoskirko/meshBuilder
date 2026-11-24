"""Independently recompute time-weighted TMC from macro block CSV files (stdlib only)."""
import argparse
import csv
import json
import math
from pathlib import Path
import re
import statistics

PARAMETERS=('Rho','Mu','Cp','Lambda','TemperatureRef','HeatFlux_Sub1','HeatFlux_Sub2',
            'MassFlow','Length','GapWidth','EquivalentGapCount')


def configuration(path):
    result={}
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        key,separator,value=line.partition('=')
        if separator and key in PARAMETERS:result[key]=float(value)
    required=('Cp','Length','GapWidth','EquivalentGapCount')
    if any(k not in result or not math.isfinite(result[k]) or result[k]<=0 for k in required):
        raise ValueError('Missing/nonpositive physical configuration')
    return result


def read_block(path):
    with Path(path).open(encoding='utf-8',newline='') as stream:
        reader=csv.reader(stream);header=next(reader,None)
        if not header or header[0]!='time_s' or len(header)!=len(set(header)):
            raise ValueError(f'{path}: invalid CSV header')
        rows=[]
        for row in reader:
            if len(row)!=len(header):raise ValueError(f'{path}: incomplete row')
            values=[float(v) for v in row]
            if not all(math.isfinite(v) for v in values):raise ValueError(f'{path}: nonfinite sample')
            if rows and values[0]<=rows[-1][0]:raise ValueError(f'{path}: non-increasing time')
            rows.append(values)
        if len(rows)<2:raise ValueError(f'{path}: insufficient samples')
    return header,rows


def summarize(header,rows,params):
    duration=rows[-1][0]-rows[0][0]
    if duration<=0:raise ValueError('Nonpositive duration')
    integrals=[0.]*(len(header)-1)
    for a,b in zip(rows,rows[1:]):
        dt=b[0]-a[0]
        if dt<=0:raise ValueError('Non-increasing time')
        for i in range(len(integrals)):integrals[i]+=.5*(a[i+1]+b[i+1])*dt
    means={key:integrals[i]/duration for i,key in enumerate(header[1:])}
    def mean(key):return means['TMC_'+key]
    def storage(sub):
        i=header.index(f'TMC_Sub{sub}_SensibleEnergy')
        return (rows[-1][i]-rows[0][i])/duration
    hot=mean('Sub2_Exchange_NoStorage')-storage(2)
    cold=-(mean('Sub1_Exchange_NoStorage')-storage(1))
    delta=mean('DeltaT_BulkLength');mass=mean('MassFluxRef')
    if hot<=0 or delta<=0 or mass<=0:raise ValueError('Invalid hot/cold direction or reference flow')
    beta=hot/(params['EquivalentGapCount']*params['GapWidth']*params['Length']*params['Cp']*mass*delta)
    return dict(start_s=rows[0][0],end_s=rows[-1][0],duration_s=duration,samples=len(rows),
                means=means,storage_sub1_W=storage(1),storage_sub2_W=storage(2),
                thermal_residual_with_storage_W=mean('EnergyResidual_NoStorage')-storage(1)-storage(2),
                exchange_hot_W=hot,exchange_cold_W=cold,exchange_mismatch_W=hot-cold,TMC_effective=beta)


def analyse(directory):
    directory=Path(directory);params=configuration(directory/'configuration.txt')
    files=sorted(((int(m.group(1)),p) for p in directory.iterdir()
                  if (m:=re.fullmatch(r'block_(\d+)\.csv',p.name))),key=lambda item:item[0])
    if not files:raise ValueError('No completed block CSV files')
    blocks=[];all_rows=[];expected=None
    for expected_number,(number,path) in enumerate(files,1):
        if number!=expected_number:raise ValueError('Missing statistics block')
        header,rows=read_block(path)
        if expected is None:expected=header
        if header!=expected:raise ValueError('Different report schema across blocks')
        if all_rows:
            if abs(rows[0][0]-all_rows[-1][0])>1e-9:raise ValueError('Gap/overlap between blocks')
            if any(abs(a-b)>1e-8*max(1,abs(a),abs(b)) for a,b in zip(rows[0][1:],all_rows[-1][1:])):
                raise ValueError('Discontinuous boundary sample between blocks')
        blocks.append(summarize(header,rows,params))
        all_rows.extend(rows[1:] if all_rows else rows)
    total=summarize(expected,all_rows,params)
    coefficients=[b['TMC_effective'] for b in blocks]
    total['blocks']=blocks
    total['block_TMC_standard_deviation']=statistics.stdev(coefficients) if len(coefficients)>1 else None
    total['last_block_relative_change']=(abs(coefficients[-1]-coefficients[-2])/abs(coefficients[-2]) if len(coefficients)>1 else None)
    total['uncertainty_note']='Block scatter is not a confidence interval; check stationarity and block independence.'
    return total


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('series',type=Path)
    parser.add_argument('--output',type=Path);args=parser.parse_args()
    result=analyse(args.series);text=json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)
    if args.output:args.output.write_text(text+'\n',encoding='utf-8')
    else:print(text)


if __name__=='__main__':main()

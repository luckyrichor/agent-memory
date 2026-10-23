"""Linux load-host resource monitor; no request bodies or credentials are read."""
import argparse,json,time
from pathlib import Path


def cpu():
 values=list(map(int,Path('/proc/stat').read_text().splitlines()[0].split()[1:]))
 return sum(values),values[3]+values[4]

def main():
 p=argparse.ArgumentParser();p.add_argument('--pid',type=int,required=True);p.add_argument('--seconds',type=int,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 if '.local' not in a.output.resolve().parts or a.output.exists():p.error('fresh private output required')
 previous=cpu();samples=[]
 for _ in range(a.seconds):
  time.sleep(1);current=cpu();delta=current[0]-previous[0];busy=1-(current[1]-previous[1])/delta if delta else None;previous=current
  info={line.split(':')[0]:int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith(('MemTotal:','MemAvailable:'))}
  memory=1-info['MemAvailable']/info['MemTotal'];rss=None
  status=Path(f'/proc/{a.pid}/status')
  if status.exists():
   rss=next((int(line.split()[1]) for line in status.read_text().splitlines() if line.startswith('VmRSS:')),None)
  samples.append({'unix_time':time.time(),'host_cpu_fraction':busy,'host_memory_fraction':memory,'load_process_rss_kib':rss})
 a.output.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 result={'samples':samples,'threshold':.7,'invalid':any((s['host_cpu_fraction'] or 0)>.7 or s['host_memory_fraction']>.7 for s in samples),'scope':'host CPU and memory; process RSS supplementary; full point invalid if host exceeds approximately70%','process_pid':a.pid}
 a.output.write_text(json.dumps(result,indent=2)+'\n');a.output.chmod(0o600)
 print(json.dumps({'samples':len(samples),'invalid':result['invalid']}))

if __name__=='__main__':main()

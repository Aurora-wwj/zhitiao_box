"""Read-only validation of the received public release, no hardware or API I/O."""
import ast,hashlib,json,re,xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
 report=json.loads((ROOT/'data/final_run_sanitized.json').read_text(encoding='utf-8'))
 assert report['decision']=='PASS' and report['evidence_source']=='real'
 assert report['verification_scope']=='gpio_period_and_uart_capture'
 assert len(report['cycles'])==2
 for index,cycle in enumerate(report['cycles']):
  rows=cycle['execution']['audit']
  assert [x['tool_name'] for x in rows]==['build_firmware','flash_firmware','read_target_log','run_hardware_test']
  assert all(x['result']['success'] for x in rows)
  result=rows[3]['result']; period=result['measurements']['period_ms']
  assert result['observation']['freshness_verified'] is True and result['observation']['fresh_edges']>=2
  assert (abs(period-1000)<=50)==result['passed']
  assert period==[601.7169,1001.08682][index]
  assert rows[0]['result']['artifact_sha256']==rows[1]['result']['artifact_sha256']
  assert rows[1]['result']['upload_verified'] is True and rows[1]['result']['verified'] is True
  assert rows[1]['result']['remote_sha256']==rows[0]['result']['artifact_sha256']
  uart=rows[2]['result'];assert not uart['overflow'] and not uart['truncated']
  assert not any(uart.get(k,0) for k in ('decoding_errors','frame_errors','parity_errors'))
 assert report['cycles'][0]['execution']['audit'][2]['result']['partial_tail'] is True
 project=ROOT/'src/stm32/gpio_pl_test'; source=project/'Core/Src/main.c'
 expected='79f6deb58231d3bc2cef887154c136a74e0da9e839a26ea41fd9468e205633cd'
 assert digest(source)==expected==report['checkpoint']['source_hashes']['Core/Src/main.c']
 assert hashlib.sha256(report['cycles'][0]['model_decision']['edit']['content'].encode()).hexdigest()==expected
 assert digest(ROOT/'build/stm32/firmware.hex')==report['cycles'][1]['execution']['audit'][0]['result']['artifact_sha256']
 manifest=json.loads((ROOT/'data/stm32_sha256.json').read_text())
 for name,sha in manifest.items():assert digest(ROOT/name)==sha,name
 tree=ET.parse(project/'MDK-ARM/GPIO_PL_Test.uvprojx')
 for node in tree.findall('.//FilePath'):
  path=(project/'MDK-ARM'/node.text.replace('\\','/')).resolve()
  assert path.is_relative_to(project.resolve()) and path.is_file(),node.text
 archive=ROOT/'sim/smoke/manifest.json'
 if archive.exists():
  for entry in json.loads(archive.read_text(encoding='utf-8'))['files']:
   name=entry['public_name']
   assert Path(name).name==name and name.endswith('.py.txt'),name
   path=archive.parent/name
   assert digest(path)==entry['public_sha256'],name
   ast.parse(path.read_text(encoding='utf-8'),filename=name)
 for p in ROOT.rglob('*'):
  if '.git' in p.relative_to(ROOT).parts or not p.is_file():continue
  name=p.name.lower()
  assert name not in ('dropbear_rsa_host_key','id_rsa','id_ed25519','id_ecdsa'),str(p)
  assert not name.startswith('deployment.local'),str(p)
 print('PASS: final JSON / two complete cycles / source and HEX SHA / Keil inputs / historical archive / forbidden filenames')
if __name__=='__main__':main()

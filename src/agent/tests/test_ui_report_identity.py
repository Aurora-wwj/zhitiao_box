"""Exercise report labels against the actual frontend JavaScript, offline."""
import json
import re
import shutil
import subprocess
import unittest

from zhidiao_agent.ui_page import HTML


@unittest.skipUnless(shutil.which('node'), 'JavaScript runtime is unavailable')
class ReportIdentityTests(unittest.TestCase):
    def run_frontend(self, actions):
        script = re.search(r'<script[^>]*>(.*?)</script>', HTML, re.S).group(1)
        script = script.replace('refresh();setInterval(refresh,1000);', '')
        fixture = '''
const fixtureElements = new Map();
function fixtureElement() {return {textContent:'',value:'',children:[],className:'',
  classList:{toggle(){}},replaceChildren(...nodes){this.children=nodes;},
  append(...nodes){this.children.push(...nodes);},appendChild(child){this.children.push(child);return child;}};}
global.document = {getElementById(id){if(!fixtureElements.has(id))fixtureElements.set(id,fixtureElement());return fixtureElements.get(id);},
  createElement(){return fixtureElement();}};
global.fetch = () => {throw new Error('Report display must not send a request');};
'''
        result = subprocess.run([shutil.which('node'), '-e', fixture + script + actions],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_history_selection_does_not_change_current_report_or_results(self):
        result = self.run_frontend('''
const fixtureState={phase:'PASS',busy:false,preflight:{success:true},scope:{},
  report:{run_id:'run_current',decision:'PASS'},view:{measurements:[{attempt:2,period_ms:1001.08682,passed:true}],steps:[]}};
el('runs').value='run_historical';selectRun();render(fixtureState);
const initial={current:el('current-run-id').textContent,selected:el('selected-run-id').textContent,
  report:JSON.parse(el('report').textContent),href:el('old-report').href,
  period:el('rounds').children[0].children[1].textContent};
el('runs').value='run_another';selectRun();
const unchanged=JSON.parse(el('report').textContent);
render({...fixtureState,report:{run_id:'run_new_current',decision:'PASS'}});
process.stdout.write(JSON.stringify({initial,unchanged,current:el('current-run-id').textContent,
  selected:el('selected-run-id').textContent,href:el('old-report').href}));
''')
        self.assertEqual(result['initial']['current'], 'run_current')
        self.assertEqual(result['initial']['selected'], 'run_historical')
        self.assertEqual(result['initial']['period'], '1001.087 ms')
        self.assertEqual(result['initial']['href'], '/api/report/run_historical')
        self.assertEqual(result['unchanged'], result['initial']['report'])
        self.assertEqual(result['current'], 'run_new_current')
        self.assertEqual(result['selected'], 'run_another')
        self.assertEqual(result['href'], '/api/report/run_another')

    def test_empty_labels_and_text_only_untrusted_identifier(self):
        result = self.run_frontend('''
render({phase:'IDLE',busy:false,preflight:{success:true},scope:{},report:{},view:{steps:[]}});
selectRun();const empty=[el('current-run-id').textContent,el('selected-run-id').textContent];
el('runs').value='<img src=x onerror=alert(1)>';selectRun();
process.stdout.write(JSON.stringify({empty,label:el('selected-run-id').textContent,
  href:el('old-report').href,children:el('selected-run-id').children.length}));
''')
        self.assertEqual(result['empty'], ['尚未生成报告', '未选择'])
        self.assertEqual(result['label'], '<img src=x onerror=alert(1)>')
        self.assertEqual(result['children'], 0)
        self.assertIn('%3Cimg', result['href'])


if __name__ == '__main__':
    unittest.main()

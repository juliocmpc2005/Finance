"""The program version sent to AEAT changes whenever the code with fiscal effect changes."""
import io, json, runpy, sys, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from backend import fiscal_version as fiscal
from backend.verifactu_xml import SYSTEM

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = str(ROOT / 'scripts' / 'fiscal-fingerprint.py')

class FiscalVersionTests(unittest.TestCase):
    def test_fiscal_code_matches_the_registered_program_version(self):
        registry = fiscal.registry()
        self.assertEqual(registry['version'], SYSTEM['version'],
            'La versión enviada a la AEAT no coincide con la registrada. Ejecuta: python3 scripts/fiscal-fingerprint.py --update')
        self.assertEqual(registry['fingerprint'], fiscal.fingerprint(),
            f"Ha cambiado código con efecto fiscal (VERI*FACTU) y la versión sigue siendo {SYSTEM['version']}. "
            "Sube SYSTEM['version'] en backend/verifactu_xml.py, actualiza la declaración responsable y ejecuta "
            'python3 scripts/fiscal-fingerprint.py --update (o --keep-version "motivo" si el cambio no tiene efecto fiscal).')
    def test_every_fiscal_fragment_is_marked_and_counted(self):
        names = [name for name, _ in fiscal.sources()]
        for expected in ['backend/verifactu.py', 'backend/verifactu_xml.py', 'backend/verifactu_specs/SuministroLR.xsd', 'serve.py#0', 'serve.py#1', 'dist/templates.js#0', 'dist/styles.css#0']:
            self.assertIn(expected, names)
        self.assertIn('ValidarQR', dict(fiscal.sources())['backend/verifactu_xml.py']);self.assertIn('35mm', dict(fiscal.sources())['dist/styles.css#0'])
    def run_script(self, registry, *arguments, current='changed'):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'fiscal-version.json'; path.write_text(json.dumps(registry), encoding='utf-8')
            output = io.StringIO()
            with patch.object(fiscal, 'REGISTRY', path), patch.object(fiscal, 'fingerprint', return_value=current), patch.object(sys, 'argv', [SCRIPT, *arguments]), redirect_stdout(output):
                try: runpy.run_path(SCRIPT, run_name='__main__'); code = 0
                except SystemExit as exit: code = exit.code
            return code, output.getvalue(), json.loads(path.read_text(encoding='utf-8'))
    def test_a_fiscal_change_cannot_be_registered_with_the_same_version(self):
        same = {'version': SYSTEM['version'], 'fingerprint': 'old', 'history': []}
        code, _, saved = self.run_script(same, '--update')
        self.assertIn('Sube SYSTEM', str(code)); self.assertEqual(saved['fingerprint'], 'old')
        code, _, saved = self.run_script(same, '--update', '--keep-version', 'corto')
        self.assertIn('motivo', str(code)); self.assertEqual(saved['fingerprint'], 'old')
        code, _, saved = self.run_script(same, '--update', '--keep-version', 'Solo cambia el texto de una ayuda')
        self.assertEqual((code, saved['fingerprint'], saved['history'][-1]['note']), (0, 'changed', 'Solo cambia el texto de una ayuda'))
    def test_a_new_version_is_registered_and_the_check_reports_differences(self):
        code, _, saved = self.run_script({'version': '0.9.0', 'fingerprint': 'old', 'history': []}, '--update')
        self.assertEqual((code, saved['version'], saved['fingerprint']), (0, SYSTEM['version'], 'changed'))
        self.assertIn('declaración responsable', saved['history'][-1]['note'])
        code, output, _ = self.run_script({'version': SYSTEM['version'], 'fingerprint': 'old', 'history': []})
        self.assertEqual(code, 1); self.assertIn('huella distinta', output)

if __name__ == '__main__': unittest.main()

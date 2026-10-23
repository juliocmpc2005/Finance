"""Records the fiscal fingerprint of the current program version (backend/fiscal-version.json).

Usage, from the project folder:
  python3 scripts/fiscal-fingerprint.py                     # check only
  python3 scripts/fiscal-fingerprint.py --update            # after raising SYSTEM['version'] in backend/verifactu_xml.py
  python3 scripts/fiscal-fingerprint.py --update --keep-version "motivo"
                                                            # same version: only for changes without fiscal effect

A new version needs a declaración responsable that covers it before any real VERI*FACTU submission.
"""
import argparse, json, sys
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import fiscal_version as fiscal
from backend.verifactu_xml import SYSTEM

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument('--update', action='store_true', help='registrar la huella actual')
parser.add_argument('--keep-version', metavar='MOTIVO', help='mantener la versión: el cambio no tiene efecto fiscal')
args = parser.parse_args()

current = fiscal.fingerprint()
data = fiscal.registry() if fiscal.REGISTRY.exists() else {'version': None, 'fingerprint': None, 'history': []}
version = SYSTEM['version']
if not args.update:
    ok = data['version'] == version and data['fingerprint'] == current
    print(f"Versión del programa: {version} · registrada: {data['version']} · huella {'coincide' if data['fingerprint'] == current else 'distinta'}")
    sys.exit(0 if ok else 1)
if data['fingerprint'] == current and data['version'] == version:
    print('Sin cambios: la huella ya está registrada para la versión', version); sys.exit(0)
if data['version'] == version and not args.keep_version:
    sys.exit(f'El código fiscal ha cambiado y la versión sigue siendo {version}.\n'
             f"Sube SYSTEM['version'] en backend/verifactu_xml.py y actualiza la declaración responsable,\n"
             f'o, si el cambio no tiene efecto fiscal, repite con --keep-version "motivo".')
if args.keep_version is not None and len(args.keep_version.strip()) < 10:
    sys.exit('Explica el motivo (al menos 10 caracteres): quedará en el historial.')
entry = {'version': version, 'fingerprint': current, 'date': date.today().isoformat(),
         'note': args.keep_version.strip() if args.keep_version else 'Nueva versión: requiere declaración responsable que la cubra.'}
data.update(version=version, fingerprint=current); data['history'].append(entry)
fiscal.REGISTRY.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('Registrada la huella fiscal de la versión', version)

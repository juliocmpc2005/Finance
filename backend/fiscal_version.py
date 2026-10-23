"""Fingerprint of the code with fiscal effect, tied to the program version declared to AEAT.

Every VERI*FACTU record carries the program version (verifactu_xml.SYSTEM), and the producer's
declaración responsable must cover that version. A change in this code therefore requires a new
version (and an updated declaration), unless the change has no fiscal effect and that is recorded.
Registry: backend/fiscal-version.json. Update: python3 scripts/fiscal-fingerprint.py.
"""
import hashlib, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / 'backend' / 'fiscal-version.json'
# Whole files, and fragments between «fiscal-fingerprint:start» and «fiscal-fingerprint:end» markers.
FILES = ['backend/verifactu.py', 'backend/verifactu_xml.py', 'backend/fiscal_version.py']
SPECS = 'backend/verifactu_specs'
FRAGMENTS = ['serve.py', 'dist/templates.js', 'dist/styles.css']
MARKED = re.compile(r'fiscal-fingerprint:start.*?fiscal-fingerprint:end', re.S)

def sources():
    """(path, text) of every fiscal source, in a stable order; line endings do not count."""
    result = [(path, (ROOT / path).read_text(encoding='utf-8')) for path in FILES]
    result += [(str(path.relative_to(ROOT)), path.read_text(encoding='utf-8')) for path in sorted((ROOT / SPECS).iterdir()) if path.is_file()]
    for path in FRAGMENTS:
        blocks = MARKED.findall((ROOT / path).read_text(encoding='utf-8'))
        if not blocks: raise ValueError(f'{path} no contiene las marcas fiscal-fingerprint.')
        result += [(f'{path}#{n}', block) for n, block in enumerate(blocks)]
    return [(path, text.replace('\r\n', '\n')) for path, text in result]

def fingerprint():
    digest = hashlib.sha256()
    for path, text in sources():
        digest.update(path.encode() + b'\0' + text.encode('utf-8') + b'\0')
    return digest.hexdigest()

def registry():
    return json.loads(REGISTRY.read_text(encoding='utf-8'))

"""Static files answer byte ranges, which Safari and iOS need to play the guide video."""
import os, socket, subprocess, tempfile, time, unittest, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class StaticRangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(); sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]; sock.close()
        cls.url = f'http://127.0.0.1:{port}'
        cls.process = subprocess.Popen(['python3', 'serve.py'], cwd=ROOT, env={**os.environ, 'ADG_DATA_DIR': cls.temp.name, 'ADG_PORT': str(port), 'ADG_PUBLIC_ORIGIN': '', 'ADG_VERIFACTU_NETWORK': 'off'}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try: urllib.request.urlopen(cls.url + '/api/auth/session'); break
            except Exception: time.sleep(.05)
        cls.full = (ROOT / 'dist' / 'styles.css').read_bytes()
    @classmethod
    def tearDownClass(cls): cls.process.terminate(); cls.process.wait(); cls.temp.cleanup()
    def get(self, header=None):
        request = urllib.request.Request(self.url + '/styles.css', headers={'Range': header} if header else {})
        try: response = urllib.request.urlopen(request)
        except urllib.error.HTTPError as error: response = error
        with response: return response.status, response.headers, response.read()
    def test_ranges(self):
        size = len(self.full)
        status, headers, body = self.get()
        self.assertEqual((status, body, headers['Accept-Ranges']), (200, self.full, 'bytes'))
        status, headers, body = self.get('bytes=0-9')
        self.assertEqual((status, body, headers['Content-Range'], headers['Content-Length']), (206, self.full[:10], f'bytes 0-9/{size}', '10'))
        status, headers, body = self.get('bytes=-5')
        self.assertEqual((status, body, headers['Content-Range']), (206, self.full[-5:], f'bytes {size-5}-{size-1}/{size}'))
        status, headers, body = self.get(f'bytes={size-3}-')
        self.assertEqual((status, body), (206, self.full[-3:]))
        status, headers, _ = self.get(f'bytes={size}-')
        self.assertEqual((status, headers['Content-Range']), (416, f'bytes */{size}'))
        self.assertEqual(self.get('bytes=a-b')[0], 200)

if __name__ == '__main__': unittest.main()

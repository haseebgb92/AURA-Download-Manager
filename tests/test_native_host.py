import io
import json
import pathlib
import struct
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'desktop/common'))
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'scripts'))
import native_host
import register_native_host
import windows_registration

class NativeHostTests(unittest.TestCase):
    def test_framing_and_unicode(self):
        b=io.BytesIO()
        native_host.write_frame(b,{'ok':True,'name':'AURA ∞'})
        b.seek(0)
        self.assertEqual(native_host.read_frame(b),{'ok':True,'name':'AURA ∞'})
    def test_large_frame_rejected(self):
        with self.assertRaises(ValueError):
            native_host.read_frame(io.BytesIO(struct.pack('=I',native_host.MAX_MESSAGE+1)))
    def test_reject_unsafe_request(self):
        for payload in [
          {'command':'delete','url':'https://example.com'},
          {'command':'add','url':'file:///etc/passwd'},
          {'command':'add','url':'https://name:secret@example.com/download'},
          {'command':'stream','url':'https://example.com/a','kind':'unsafe'}
        ]:
            self.assertFalse(native_host.process_message(payload)['ok'])
    def test_status_response_does_not_return_secret(self):
        class FakeResp:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,size):return b'{"ok":true,"platform":"linux"}'
        with tempfile.TemporaryDirectory() as d:
            key=pathlib.Path(d)/'bridge.token'
            key.write_text('a'*48)
            with mock.patch.object(native_host,'TOKEN_PATH',key),mock.patch.object(native_host.urllib.request,'urlopen',return_value=FakeResp()) as send:
                res=native_host.process_message({'command':'status'})
                self.assertTrue(res['ok'])
                request=send.call_args.args[0]
                self.assertEqual(request.headers['X-aura-token'],'a'*48)
                self.assertNotIn('token',json.dumps(res))
    def test_windows_extension_id_matching_requires_actual_aura_worker(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d)
            trusted=root/'package'/'chrome'
            trusted.mkdir(parents=True)
            (trusted/'worker.js').write_bytes(b"AURA native extension code")
            installed=root/'installed'/'chrome'
            installed.mkdir(parents=True)
            (installed/'worker.js').write_bytes(b"AURA native extension code")
            (installed/'manifest.json').write_text(json.dumps({
                'name':'AURA Download Manager','permissions':['nativeMessaging']}))
            rogue=root/'rogue'
            rogue.mkdir()
            (rogue/'worker.js').write_text("other browser code")
            (rogue/'manifest.json').write_text(json.dumps({
                'name':'AURA Download Manager','permissions':['nativeMessaging']}))
            prefs=root/'user-data'/'Default'/'Preferences'
            prefs.parent.mkdir(parents=True)
            valid='dmijemiijbaajeeogoepdjhejgohipcd'
            bad='a'*32
            prefs.write_text(json.dumps({'extensions':{'settings':{
                valid:{'path':str(installed)},bad:{'path':str(rogue)}
            }}}))
            ids=windows_registration.get_matching_extensions(root/'user-data',trusted)
            self.assertEqual(ids,[valid])

    def test_automatic_chrome_registration_is_exact(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d)
            ext=root/'chrome';ext.mkdir()
            prefs=root/'browser'/'Default'/'Preferences'
            prefs.parent.mkdir(parents=True)
            valid='dmijemiijbaajeeogoepdjhejgohipcd'
            malicious='a'*32
            prefs.write_text(json.dumps({'extensions':{'settings':{
                valid:{'path':str(ext)},
                malicious:{'path':str(root/'other')}
            }}}))
            result=register_native_host.register_linux(root/'host',ext,root,root/'browser')
            self.assertEqual(result['chrome_ids'],[valid])
            chrome=json.loads((root/'.config/google-chrome/NativeMessagingHosts/com.advertpreneur.aura.json').read_text())
            self.assertEqual(chrome['allowed_origins'],[f'chrome-extension://{valid}/'])
            self.assertNotIn('bridge.token',json.dumps(chrome))
            ff=json.loads((root/'.mozilla/native-messaging-hosts/com.advertpreneur.aura.json').read_text())
            self.assertEqual(ff['allowed_extensions'],['aura-download-manager@local'])

if __name__=='__main__':unittest.main()

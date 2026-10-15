import base64
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
sys.path.insert(0, str(ROOT))
import install_assistant as pc
import robot_install as robot
import verify_robot


SHA = 'a' * 40
REQUEST = {'action': 'check', 'tag': 'v1.2.3', 'commit': SHA, 'directory': 'robot'}


class InputTests(unittest.TestCase):
    def test_invalid_release_and_shell_arguments_rejected(self):
        for tag in ('main', '-v1.0.0', 'v1.0.0; touch /tmp/x', 'refs/tags/v1', 'v1.0.0\n'):
            with self.subTest(tag=tag), self.assertRaises(robot.InstallError):
                robot.validate_release(tag, SHA)
        for sha in ('HEAD', 'a'*39, 'g'*40):
            with self.assertRaises(robot.InstallError): robot.validate_release('v1.0.0', sha)

    def test_hosts_and_ports_are_not_ssh_options(self):
        for host in ('-oProxyCommand=evil', 'user@host;evil', 'user@host\n', 'user name@host'):
            with self.assertRaises(robot.InstallError): pc.ssh_command(host, 22, REQUEST)
        with self.assertRaises(robot.InstallError): pc.ssh_command('pi@robot.local', 0, REQUEST)
        command = pc.ssh_command('pi@192.168.4.1', 22, REQUEST)
        self.assertIn('StrictHostKeyChecking=ask', command)
        self.assertIn('-T', command)
        self.assertNotIn('StrictHostKeyChecking=no', command)

    def test_remote_command_is_one_quoted_python_program(self):
        import shlex
        command = pc.ssh_command('pi@robot.local', 22, {**REQUEST, 'directory': "robot'; echo nope"})
        parts = shlex.split(command[-1])
        self.assertEqual(parts[:2], ['python3', '-c'])
        self.assertEqual(len(parts), 3)
        compile(parts[2], '<ssh-program>', 'exec')

    def test_completion_html_escapes_fields_and_excludes_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'done.html'
            pc.write_completion(path, {'success': True, 'url': robot.APP_URL, 'device_name': '<script>bad</script>',
                'ssid': 'Robot', 'tag': 'v1.2.3', 'commit': SHA, 'pin': 'DO_NOT_COPY', 'wifi_password': 'DO_NOT_COPY'})
            text = path.read_text()
            self.assertIn('&lt;script&gt;', text)
            self.assertNotIn('<script>', text)
            self.assertNotIn('DO_NOT_COPY', text)
            self.assertIn(robot.APP_URL, text)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                pc.write_completion(path, {'success': True, 'url': robot.APP_URL})

    def test_qr_failure_keeps_manual_address(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'done.html'
            pc.write_completion(path, {'success': True, 'url': robot.APP_URL, 'qr_svg_base64': '!bad!'})
            self.assertIn(robot.APP_URL, path.read_text())
            self.assertNotIn('<img', path.read_text())

    def test_result_marker_required(self):
        self.assertEqual(pc.result_from('build log\nLEKIWI_RESULT={"success":true}\n'), {'success': True})
        with self.assertRaises(robot.InstallError): pc.result_from('process finished')

    def test_ssh_failure_does_not_leak_stderr(self):
        stderr, stdout = io.StringIO(), io.StringIO()
        with patch.object(pc.subprocess, 'run', return_value=subprocess.CompletedProcess([], 255, '', 'PRIVATE_TOKEN')), \
             contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(stdout):
            code = pc.main(['--host', 'pi@localhost', '--tag', 'v1.2.3', '--commit', SHA])
        self.assertEqual(code, 1)
        self.assertNotIn('PRIVATE_TOKEN', stderr.getvalue()+stdout.getvalue())
        self.assertIn('SSH', stderr.getvalue())

    def test_invalid_profile_blocks_before_ssh(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp)/'profile.yaml'; profile.write_text('lekiwi_node: {}')
            with patch.object(pc.subprocess, 'run') as ssh, patch.object(sys.stdin,'isatty',return_value=True), contextlib.redirect_stderr(io.StringIO()):
                code = pc.main(['--host', 'pi@localhost', '--tag', 'v1.2.3', '--commit', SHA,
                    '--install', '--profile', str(profile), '--serial-port', '/dev/null', '--confirm-wheel-map'])
            self.assertEqual(code, 1); ssh.assert_not_called()

    def test_pc_install_success_and_service_failure_result_handling(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'complete.html'
            args = ['--host','pi@robot.local','--tag','v1.2.3','--commit',SHA,'--install',
                '--profile',str(ROOT/'profiles/standard-sts3215.yaml'),'--serial-port','/dev/ttyUSB0',
                '--confirm-wheel-map','--output',str(output)]
            result = {'success':True,'url':robot.APP_URL,'tag':'v1.2.3','commit':SHA,'device_name':'Fixture','ssid':'Fixture AP'}
            runs = [subprocess.CompletedProcess([],0,'LEKIWI_RESULT='+json.dumps(REQUEST),''),
                    subprocess.CompletedProcess([],0,'LEKIWI_RESULT='+json.dumps(result),'')]
            with patch.object(sys.stdin,'isatty',return_value=True), patch.object(pc.subprocess,'run',side_effect=runs), \
                 patch.object(pc.subprocess,'call',return_value=0), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(pc.main(args),0)
            self.assertTrue(output.is_file())
            output.unlink()
            with patch.object(sys.stdin,'isatty',return_value=True), \
                 patch.object(pc.subprocess,'run',return_value=runs[0]), patch.object(pc.subprocess,'call',return_value=1), \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(pc.main(args),1)
            self.assertFalse(output.exists())


class RemotePreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.home = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        patches = [patch.object(Path, 'home', return_value=self.home),
            patch.object(robot.os, 'geteuid', return_value=1000),
            patch.object(robot.platform, 'freedesktop_os_release', return_value={'ID':'ubuntu','VERSION_ID':'24.04','PRETTY_NAME':'Ubuntu'}),
            patch.object(robot.platform, 'machine', return_value='aarch64'),
            patch.object(robot.shutil, 'which', side_effect=lambda value:'/usr/bin/'+value),
            patch.object(robot.socket, 'getaddrinfo', return_value=[('ok',)]),
            patch.object(robot.urllib.request, 'urlopen')]
        self.mocks = [p.start() for p in patches]
        for p in patches: self.addCleanup(p.stop)
        self.mocks[-1].return_value.__enter__.return_value.status = 200
        self.runner = patch.object(robot, 'run', side_effect=self.command).start()
        self.addCleanup(patch.stopall)

    def command(self, args, *a, **kw):
        if args[:2] == ['ip', '-j']: return '[{"gateway":"192.168.1.1"}]'
        if args[:2] == ['git', 'ls-remote']: return SHA+'\trefs/tags/v1.2.3'
        if args == ['git', '--version']: return 'git version test'
        raise AssertionError(args)

    def test_preflight_without_mutation(self):
        result = robot.inspect(REQUEST)
        self.assertEqual(result['commit'], SHA)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_existing_installation_refused(self):
        (self.home/'robot').mkdir()
        with self.assertRaisesRegex(robot.InstallError, '기존'): robot.inspect(REQUEST)

    def test_unsupported_os_and_architecture_refused(self):
        self.mocks[3].return_value = 'x86_64'
        with self.assertRaisesRegex(robot.InstallError, 'ARM64'): robot.inspect(REQUEST)

    def test_git_missing(self):
        self.mocks[4].side_effect = lambda value: None if value == 'git' else '/usr/bin/'+value
        with self.assertRaisesRegex(robot.InstallError, 'git 미설치'): robot.inspect(REQUEST)

    def test_no_gateway(self):
        self.runner.side_effect = lambda args: '[]'
        with self.assertRaisesRegex(robot.InstallError, '게이트웨이'): robot.inspect(REQUEST)

    def test_dns_failure(self):
        self.mocks[5].side_effect = OSError()
        with self.assertRaisesRegex(robot.InstallError, 'DNS'): robot.inspect(REQUEST)

    def test_internet_tls_failure(self):
        self.mocks[6].side_effect = OSError('TLS failure')
        with self.assertRaisesRegex(robot.InstallError, '네트워크'): robot.inspect(REQUEST)

    def test_invalid_or_moved_tag(self):
        with patch.object(robot, 'resolve_tag', return_value='b'*40):
            with self.assertRaisesRegex(robot.InstallError, '일치'): robot.inspect(REQUEST)

    def test_path_traversal_and_symlink_escape(self):
        for value in ('../escape', '/tmp/path', '.ssh/project', '.'):
            with self.assertRaises(robot.InstallError): robot.target_path(value)
        (self.home/'escape').symlink_to('/tmp')
        with self.assertRaises(robot.InstallError): robot.target_path('escape/robot')

    def test_annotated_tag_uses_peeled_commit(self):
        self.runner.side_effect = None
        self.runner.return_value = 'b'*40+'\trefs/tags/v1.2.3\n'+SHA+'\trefs/tags/v1.2.3^{}'
        self.assertEqual(robot.resolve_tag('v1.2.3'), SHA)


class GitReleaseIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.home = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.source = self.home/'upstream'; self.source.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Fixture'); self.git('config', 'user.email', 'fixture@example.invalid')
        (self.source/'requirements-test.txt').write_text('PyYAML==6.0.3\n')
        self.git('add', '.'); self.git('commit', '-qm', 'initial fixture')
        self.sha = self.git('rev-parse', 'HEAD')
        self.git('tag', '-a', 'v1.2.3', '-m', 'fixture release')

    def git(self, *args, cwd=None):
        return subprocess.check_output(['git', *args], cwd=cwd or self.source, text=True, stderr=subprocess.DEVNULL).strip()

    def test_clone_real_tag_and_preserve_external_settings_and_recordings(self):
        (self.home/'config').write_text('private setting'); (self.home/'recordings').mkdir()
        (self.home/'recordings'/'episode.json').write_text('recording')
        with patch.object(Path, 'home', return_value=self.home), patch.object(robot, 'REPOSITORY', str(self.source)):
            self.assertEqual(robot.resolve_tag('v1.2.3'), self.sha)
            target = robot.clone_release({**REQUEST, 'commit': self.sha})
        self.assertEqual(self.git('rev-parse', 'HEAD', cwd=target), self.sha)
        self.assertEqual(self.git('describe', '--exact-match', '--tags', cwd=target), 'v1.2.3')
        self.assertEqual((self.home/'config').read_text(), 'private setting')
        self.assertEqual((self.home/'recordings'/'episode.json').read_text(), 'recording')
        with patch.object(Path, 'home', return_value=self.home), self.assertRaises(robot.InstallError):
            robot.clone_release({**REQUEST, 'commit': self.sha})

    def test_mismatched_commit_keeps_clone_but_never_checks_out_source(self):
        with patch.object(Path, 'home', return_value=self.home), patch.object(robot, 'REPOSITORY', str(self.source)):
            with self.assertRaisesRegex(robot.InstallError, '불일치'): robot.clone_release(REQUEST)
        self.assertTrue((self.home/'robot'/'.git').exists())
        self.assertFalse((self.home/'robot'/'requirements-test.txt').exists())

    def test_dependency_change_and_manual_git_rollback(self):
        (self.source/'requirements-test.txt').write_text('PyYAML==6.0.3\nPillow==12.3.0\n')
        self.git('add', '.'); self.git('commit', '-qm', 'dependency change'); self.git('tag', 'v1.2.4')
        newer = self.git('rev-parse', 'HEAD')
        names = self.git('diff', '--name-only', self.sha, newer, '--', 'requirements-test.txt')
        self.assertEqual(names, 'requirements-test.txt')
        self.git('checkout', '--detach', self.sha)
        self.assertEqual((self.source/'requirements-test.txt').read_text(), 'PyYAML==6.0.3\n')
        self.git('checkout', '--detach', newer)
        self.assertIn('Pillow', (self.source/'requirements-test.txt').read_text())

    def test_missing_release_tag_reports_no_release(self):
        with patch.object(robot, 'REPOSITORY', str(self.source)):
            with self.assertRaisesRegex(robot.InstallError,'태그가 없습니다'): robot.resolve_tag('v9.9.9')


class InstallFailureTests(unittest.TestCase):
    def test_install_script_failure_never_marks_completed(self):
        request = {**REQUEST, 'profile_base64': base64.b64encode((ROOT/'profiles/standard-sts3215.yaml').read_bytes()).decode(),
                   'confirm_wheel_map':True, 'serial_port':'/dev/null','camera':'0'}
        def failed_install(arguments, **kwargs):
            self.assertNotIn('12345678', arguments)
            pin_path = Path(arguments[arguments.index('--pin-file')+1])
            self.assertEqual(pin_path.read_text(), '12345678')
            self.assertEqual(pin_path.stat().st_mode & 0o777, 0o600)
            return 9
        with patch.object(robot, 'inspect'), patch.object(robot, 'clone_release', return_value=ROOT), \
             patch.object(sys.stdin,'isatty',return_value=True), \
             patch.object(robot.getpass, 'getpass', return_value='12345678'), \
             patch.object(robot.subprocess, 'call', side_effect=failed_install), patch.object(robot, 'completion') as complete, \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(robot.InstallError, 'install.sh 실패'): robot.install(request)
            complete.assert_not_called()

    def test_no_tty_refused_before_changes(self):
        with patch.object(sys.stdin,'isatty',return_value=False), patch.object(robot,'inspect') as inspect:
            with self.assertRaisesRegex(robot.InstallError, 'TTY'): robot.install(REQUEST)
            inspect.assert_not_called()

    def test_service_failure(self):
        with patch.object(robot, 'run', side_effect=robot.InstallError('inactive')):
            with self.assertRaises(robot.InstallError): robot.verify_services()

    def test_version_mismatch_not_persisted(self):
        with patch.object(robot, 'verify_services'), patch.object(robot, 'run', return_value='b'*40):
            with self.assertRaisesRegex(robot.InstallError, '커밋'): robot.completion(ROOT, REQUEST)


if __name__ == '__main__':
    unittest.main()

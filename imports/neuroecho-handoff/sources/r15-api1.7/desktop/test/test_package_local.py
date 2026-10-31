"""Developer pointer/preflight only; never builds or starts a real App."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC=importlib.util.spec_from_file_location('local_builder',Path(__file__).resolve().parents[1]/'package-local.py')
builder=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(builder)


class PackageLocalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.source=self.root/'source';(self.source/'server').mkdir(parents=True)
        (self.source/'server/main.py').write_text('# synthetic source')
        (self.source/'scripts').mkdir();(self.source/'scripts/run_paired_service.py').write_text('# synthetic runner')
        self.data=self.root/'private-data';self.data.mkdir(mode=0o700)
        self.python=self.root/'runtime/python';self.python.parent.mkdir();self.python.write_text('# synthetic executable');self.python.chmod(0o755)
        self.legacy=self.source/'.venv/bin/python';self.legacy.parent.mkdir(parents=True);self.legacy.symlink_to(self.python)
        self.venv=self.root/'existing-venv/bin/python';self.venv.parent.mkdir(parents=True);self.venv.symlink_to(self.python)
        self.output=self.root/'New.app'
        self.base=['--runtime',str(self.root/'unused/Electron.app'),'--project-root',str(self.source),'--output',str(self.output)]

    def tearDown(self):self.temp.cleanup()

    def args(self,*extra):return builder.arguments(self.base+list(extra))

    def invalid(self,*extra):
        with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):self.args(*extra)
        self.assertFalse(self.output.exists(),'preflight must not create an App')

    def explicit(self):return ['--python',str(self.venv),'--backend-data-dir',str(self.data)]

    def test_pointer_preserves_venv_symlink_and_exact_selected_profile_without_copying(self):
        args=self.args(*self.explicit(),'--port','18827','--profile','isolated-desktop')
        target=self.output/'Contents/Resources/app'
        pointer=builder.project_pointer(args,target)
        self.assertEqual(pointer,{'relativeRoot':os.path.relpath(self.source,target),'port':18827,'profile':'isolated-desktop',
                                  'python':str(self.venv),'backendDataDir':str(self.data.resolve())})
        self.assertNotEqual(pointer['python'],str(self.venv.resolve()))
        self.assertFalse(self.output.exists())

    def test_old_local_pointer_remains_unchanged_without_explicit_backend_options(self):
        args=self.args();target=self.output/'Contents/Resources/app'
        self.assertEqual(builder.project_pointer(args,target),{'relativeRoot':os.path.relpath(self.source,target),'port':18787})

    def test_missing_default_venv_fails_before_runtime_copy_and_requires_both_explicit_options(self):
        self.legacy.unlink()
        for nonexecutable in (False,True):
            if nonexecutable:self.legacy.write_text('# not executable');self.legacy.chmod(0o644)
            error=io.StringIO()
            with patch.object(builder.shutil,'copytree') as copy,contextlib.redirect_stderr(error),self.assertRaises(SystemExit):builder.main(self.base)
            copy.assert_not_called();self.assertIn('--python and --backend-data-dir',error.getvalue());self.assertFalse(self.output.exists())

    def test_python_and_data_options_are_a_required_pair(self):
        self.invalid('--python',str(self.venv));self.invalid('--backend-data-dir',str(self.data))

    def test_interpreter_must_be_absolute_executable_file_but_may_be_venv_symlink(self):
        for candidate in ['relative/python',str(self.root/'missing'),str(self.python.parent)]:
            self.invalid('--python',candidate,'--backend-data-dir',str(self.data))
        self.python.chmod(0o644);self.invalid(*self.explicit())

    def test_data_directory_rejects_relative_missing_file_and_symlink(self):
        alias=self.root/'alias';alias.symlink_to(self.data,target_is_directory=True)
        plain=self.root/'plain';plain.write_text('synthetic')
        for candidate in ['relative',str(self.root/'missing'),str(alias),str(plain)]:
            self.invalid('--python',str(self.venv),'--backend-data-dir',candidate)

    def test_source_and_app_data_directories_are_rejected_including_parent_alias(self):
        inside=self.source/'data';inside.mkdir(mode=0o700)
        appdata=self.root/'Other.app/data';appdata.mkdir(parents=True,mode=0o700)
        alias=self.root/'source-alias';alias.symlink_to(self.source,target_is_directory=True)
        for candidate in [inside,appdata,alias/'data']:
            self.invalid('--python',str(self.venv),'--backend-data-dir',str(candidate))

    def test_nonprivate_data_permissions_are_never_automatically_changed(self):
        self.data.chmod(0o755);self.invalid(*self.explicit());self.assertEqual(self.data.stat().st_mode&0o777,0o755)

    def test_runner_must_exist_as_a_regular_reviewed_file(self):
        runner=self.source/'scripts/run_paired_service.py';runner.unlink();self.invalid(*self.explicit())
        runner.symlink_to(self.python);self.invalid(*self.explicit())

    def test_preflight_and_pointer_never_read_private_directory_contents(self):
        (self.data/'model-settings.json').write_text('SYNTHETIC-MUST-NOT-BE-READ')
        (self.data/'data.db').write_text('SYNTHETIC-MUST-NOT-BE-READ')
        with patch.object(Path,'read_bytes',side_effect=AssertionError('unexpected content read')),patch.object(Path,'read_text',side_effect=AssertionError('unexpected content read')):
            args=self.args(*self.explicit());builder.project_pointer(args,self.output/'Contents/Resources/app')
        self.assertEqual({p.name for p in self.data.iterdir()},{'model-settings.json','data.db'})


if __name__=='__main__':unittest.main()

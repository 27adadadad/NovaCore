"""Install the built wheel, then smoke-check it outside the source checkout."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    wheels = list(Path(sys.argv[1]).resolve().glob('*.whl'))
    if len(wheels) != 1:
        raise SystemExit('Expected exactly one wheel in a clean build directory')
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-deps', '--no-index',
                    '--force-reinstall', str(wheels[0])], check=True)
    env = dict(os.environ, DASHSCOPE_API_KEY='', AUTO_MEMORY_ENABLED='false')
    env.pop('PYTHONPATH', None)
    code = '''from pathlib import Path
import sys
import novacore
from novacore.skills import SkillLoader
assert Path(novacore.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()), novacore.__file__
loader=SkillLoader(Path.cwd(), user_skills_dir=Path.cwd()/'empty-user-skills')
loader.load_all()
assert loader.get('proposal-review') is not None
from novacore.shell_environment import shell_executable
assert Path(shell_executable()).is_file()
print('INSTALLED_WHEEL_SMOKE=passed;MODEL_REQUESTS=0')
'''
    with tempfile.TemporaryDirectory(prefix='novacore-wheel-') as d:
        subprocess.run([sys.executable, '-I', '-c', code], cwd=d, env=env, check=True)
        subprocess.run([sys.executable, '-I', '-m', 'novacore', '--help'], cwd=d, env=env, check=True)


if __name__ == '__main__':
    main()

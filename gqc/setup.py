from setuptools import setup, find_packages

with open('README.rst') as f:
    readme = f.read()

with open('LICENSE') as f:
    license = f.read()

setup(
    name='gqc',
    version='0.1.0',
    description='Gamequeer fantasy console compiler suite',
    long_description=readme,
    author='George Louthan',
    author_email='duplico@dupli.co',
    url='https://github.com/duplico/gamequeer-compiler',
    license=license,
    packages=find_packages(exclude=('tests', 'docs', 'examples'))
)

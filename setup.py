import codecs
import pathlib
import re
import sys
from distutils.command.build_ext import build_ext
from distutils.errors import (CCompilerError, DistutilsExecError,
                              DistutilsPlatformError)

from setuptools import Extension, setup
from setuptools.command.test import test as TestCommand


if sys.version_info < (3, 5, 3):
    raise RuntimeError("aiohttp 3.x requires Python 3.5.3+")


IS_CPYTHON = sys.implementation.name == "cpython"


try:
    from Cython.Build import cythonize
    USE_CYTHON = True
except ImportError:
    USE_CYTHON = False

ext = '.pyx' if USE_CYTHON else '.c'


_BROTLI_VENDOR = 'aiohttp/_vendored/brotli_src'
_brotli_sources = [
    _BROTLI_VENDOR + '/python/_brotli.c',
    _BROTLI_VENDOR + '/c/common/constants.c',
    _BROTLI_VENDOR + '/c/common/context.c',
    _BROTLI_VENDOR + '/c/common/dictionary.c',
    _BROTLI_VENDOR + '/c/common/platform.c',
    _BROTLI_VENDOR + '/c/common/shared_dictionary.c',
    _BROTLI_VENDOR + '/c/common/transform.c',
    _BROTLI_VENDOR + '/c/dec/bit_reader.c',
    _BROTLI_VENDOR + '/c/dec/decode.c',
    _BROTLI_VENDOR + '/c/dec/huffman.c',
    _BROTLI_VENDOR + '/c/dec/prefix.c',
    _BROTLI_VENDOR + '/c/dec/state.c',
    _BROTLI_VENDOR + '/c/dec/static_init.c',
    _BROTLI_VENDOR + '/c/enc/backward_references.c',
    _BROTLI_VENDOR + '/c/enc/backward_references_hq.c',
    _BROTLI_VENDOR + '/c/enc/bit_cost.c',
    _BROTLI_VENDOR + '/c/enc/block_splitter.c',
    _BROTLI_VENDOR + '/c/enc/brotli_bit_stream.c',
    _BROTLI_VENDOR + '/c/enc/cluster.c',
    _BROTLI_VENDOR + '/c/enc/command.c',
    _BROTLI_VENDOR + '/c/enc/compound_dictionary.c',
    _BROTLI_VENDOR + '/c/enc/compress_fragment.c',
    _BROTLI_VENDOR + '/c/enc/compress_fragment_two_pass.c',
    _BROTLI_VENDOR + '/c/enc/dictionary_hash.c',
    _BROTLI_VENDOR + '/c/enc/encode.c',
    _BROTLI_VENDOR + '/c/enc/encoder_dict.c',
    _BROTLI_VENDOR + '/c/enc/entropy_encode.c',
    _BROTLI_VENDOR + '/c/enc/fast_log.c',
    _BROTLI_VENDOR + '/c/enc/histogram.c',
    _BROTLI_VENDOR + '/c/enc/literal_cost.c',
    _BROTLI_VENDOR + '/c/enc/memory.c',
    _BROTLI_VENDOR + '/c/enc/metablock.c',
    _BROTLI_VENDOR + '/c/enc/static_dict.c',
    _BROTLI_VENDOR + '/c/enc/static_dict_lut.c',
    _BROTLI_VENDOR + '/c/enc/static_init.c',
    _BROTLI_VENDOR + '/c/enc/utf8_util.c',
]
_brotli_extension = Extension(
    'aiohttp._vendored._brotli',
    sources=_brotli_sources,
    include_dirs=[_BROTLI_VENDOR + '/c/include'],
    # Don't take down the whole wheel if the vendored brotli sources fail to
    # compile (e.g. on the manylinux1 toolchain). _import_vendored_brotli()
    # catches the resulting ImportError and falls back to the system brotli.
    optional=True,
)


extensions = [Extension('aiohttp._websocket', ['aiohttp/_websocket' + ext]),
              Extension('aiohttp._http_parser',
                        ['aiohttp/_http_parser' + ext,
                         'vendor/http-parser/http_parser.c'],
                        define_macros=[('HTTP_PARSER_STRICT', 0)],
                        ),
              Extension('aiohttp._frozenlist',
                        ['aiohttp/_frozenlist' + ext]),
              _brotli_extension]


if USE_CYTHON:
    extensions = cythonize(extensions)


class BuildFailed(Exception):
    pass


class ve_build_ext(build_ext):
    # This class allows C extension building to fail.

    def run(self):
        try:
            build_ext.run(self)
        except (DistutilsPlatformError, FileNotFoundError):
            raise BuildFailed()

    def build_extension(self, ext):
        try:
            build_ext.build_extension(self, ext)
        except (CCompilerError, DistutilsExecError,
                DistutilsPlatformError, ValueError):
            # Honor Extension(..., optional=True): drop just this module
            # instead of failing the whole wheel.
            if getattr(ext, 'optional', False):
                self.warn(
                    'optional extension %s failed to build; skipping' % ext.name)
                return
            raise BuildFailed()


here = pathlib.Path(__file__).parent

txt = (here / 'aiohttp' / '__init__.py').read_text('utf-8')
try:
    version = re.findall(r"^__version__ = '([^']+)'\r?$",
                         txt, re.M)[0]
except IndexError:
    raise RuntimeError('Unable to determine version.')


install_requires = ['attrs>=17.3.0', 'chardet>=2.0,<4.0',
                    'multidict>=4.0,<5.0',
                    'async_timeout>=1.2,<3.0',
                    'yarl>=1.0,<2.0']

if sys.version_info < (3, 7):
    install_requires.append('idna-ssl>=1.0')


def read(f):
    return (here / f).read_text('utf-8').strip()


class PyTest(TestCommand):
    user_options = []

    def run(self):
        import subprocess
        errno = subprocess.call([sys.executable, '-m', 'pytest', 'tests'])
        raise SystemExit(errno)


tests_require = install_requires + ['pytest', 'gunicorn', 'pytest-timeout']


args = dict(
    name='aiohttp',
    version=version,
    description='Async http client/server framework (asyncio)',
    long_description='\n\n'.join((read('README.rst'), read('CHANGES.rst'))),
    classifiers=[
        'License :: OSI Approved :: Apache Software License',
        'Intended Audience :: Developers',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Development Status :: 5 - Production/Stable',
        'Operating System :: POSIX',
        'Operating System :: MacOS :: MacOS X',
        'Operating System :: Microsoft :: Windows',
        'Topic :: Internet :: WWW/HTTP',
        'Framework :: AsyncIO',
    ],
    author='Nikolay Kim',
    author_email='fafhrd91@gmail.com',
    maintainer=', '.join(('Nikolay Kim <fafhrd91@gmail.com>',
                          'Andrew Svetlov <andrew.svetlov@gmail.com>')),
    maintainer_email='aio-libs@googlegroups.com',
    url='https://github.com/aio-libs/aiohttp/',
    license='Apache 2',
    packages=['aiohttp'],
    python_requires='>=3.5.3',
    install_requires=install_requires,
    tests_require=tests_require,
    include_package_data=True,
    ext_modules=extensions,
    cmdclass=dict(build_ext=ve_build_ext,
                  test=PyTest))

try:
    setup(**args)
except BuildFailed:
    print("************************************************************")
    print("Cannot compile C accelerator module, use pure python version")
    print("************************************************************")
    # Mirror upstream's intent: keep the vendored brotli extension
    # whenever we're on CPython. The aiohttp _vendored.brotli module
    # imports _brotli at runtime, so dropping it would break imports
    # rather than gracefully degrading.
    if IS_CPYTHON:
        args['ext_modules'] = [_brotli_extension]
        try:
            setup(**args)
        except BuildFailed:
            del args['ext_modules']
            del args['cmdclass']
            setup(**args)
    else:
        del args['ext_modules']
        del args['cmdclass']
        setup(**args)

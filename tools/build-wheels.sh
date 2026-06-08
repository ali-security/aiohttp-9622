#!/bin/bash
if [ -n "$DEBUG" ]
then
  set -x
fi
set -euo pipefail
# ref: https://coderwall.com/p/fkfaqq/safer-bash-scripts-with-set-euxo-pipefail

PYTHON_VERSIONS="cp35-cp35m cp36-cp36m"

# Avoid creation of __pycache__/*.py[c|o]
export PYTHONDONTWRITEBYTECODE=1

package_name="$1"
if [ -z "$package_name" ]
then
    &>2 echo "Please pass package name as a first argument of this script ($0)"
    exit 1
fi

arch=`uname -m`

echo
echo
echo "Compile wheels"
for PYTHON in ${PYTHON_VERSIONS}; do
    /opt/python/${PYTHON}/bin/pip install --index-url 'https://:2018-03-13T09:30:47.597421Z@time-machines-pypi.sealsecurity.io/' -r /io/requirements/wheel.txt
    # wheel.txt pins pip==9.0.1 transitively via the time-machine resolution,
    # but the manylinux1 image's preinstalled pip (20.x) hasn't been touched
    # yet at this point; it uses legacy setup.py builds for /io/, which
    # picks up the Cython installed above directly.
    /opt/python/${PYTHON}/bin/pip wheel /io/ -w /io/dist/
done

echo
echo
echo "Bundle external shared libraries into the wheels"
for whl in /io/dist/${package_name}-*-linux_${arch}.whl; do
    echo "Repairing $whl..."
    auditwheel repair --plat "manylinux1_${arch}" "$whl" -w /io/dist/
done

echo
echo
echo "Strip PEP 600 manylinux_2_X prefix from auditwheel output filenames"
# auditwheel still writes a compound platform tag like
# `manylinux_2_5_x86_64.manylinux1_x86_64` despite `--plat`. That trips up
# the cleanup glob below (`-manylinux1_` requires a DASH, the compound name
# has a DOT) and pip 9.0.1 in the test step. Rename to the legacy single
# tag so everything downstream sees `aiohttp-3.0.8-cpXX-cpXXm-manylinux1_${arch}.whl`.
for whl in /io/dist/${package_name}-*.manylinux1_${arch}.whl; do
    [ -e "$whl" ] || continue
    # Bash parameter expansion (no sed): the `*` is a shell glob that
    # consumes the `2_5` (or whatever PEP 600 version auditwheel emits).
    new="${whl/-manylinux_*_${arch}.manylinux1_${arch}.whl/-manylinux1_${arch}.whl}"
    if [ "$whl" != "$new" ]; then
        echo "Renaming $whl -> $new"
        mv "$whl" "$new"
    fi
done

echo
echo
echo "Cleanup OS specific wheels"
rm -fv /io/dist/*-linux_*.whl

echo
echo
echo "Cleanup non-$package_name wheels"
find /io/dist -maxdepth 1 -type f ! -name "$package_name"'-*-manylinux1_*.whl' -print0 | xargs -0 rm -rf

echo
echo
echo "Install packages and test"
echo "dist directory:"
ls /io/dist

for PYTHON in ${PYTHON_VERSIONS}; do
    # clear python cache
    find /io -type d -name __pycache__ -print0 | xargs -0 rm -rf

    echo
    echo -n "Test $PYTHON: "
    /opt/python/${PYTHON}/bin/python -c "import platform; print('Building wheel for {platform} platform.'.format(platform=platform.platform()))"
    # Pin setuptools<46 first: ci-wheel.txt pulls towncrier 17.8.0 → old
    # Jinja2 → MarkupSafe 1.0 sdist whose setup.py does `from setuptools
    # import Feature`, removed in setuptools 46. 45.x still has it.
    /opt/python/${PYTHON}/bin/pip install --index-url 'https://:2018-03-13T09:30:47.597421Z@time-machines-pypi.sealsecurity.io/' 'setuptools<46'
    /opt/python/${PYTHON}/bin/pip install --index-url 'https://:2018-03-13T09:30:47.597421Z@time-machines-pypi.sealsecurity.io/' -r /io/requirements/ci-wheel.txt
    /opt/python/${PYTHON}/bin/pip install --index-url 'https://:2018-03-13T09:30:47.597421Z@time-machines-pypi.sealsecurity.io/' "$package_name" --no-index -f file:///io/dist
    /opt/python/${PYTHON}/bin/py.test /io/tests
done

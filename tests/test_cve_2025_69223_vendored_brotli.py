import subprocess
import sys
import textwrap

import pytest

from aiohttp.http_parser import (
    DEFAULT_MAX_DECOMPRESS_SIZE,
    HAS_BROTLI,
    BrotliDecompressor,
)

try:
    import brotli as _system_brotli
except ImportError:  # pragma: no cover
    _system_brotli = None  # type: ignore[assignment]


def _run_py(code: str) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )


def _ver(mod: object) -> "tuple[int, int]":
    # brotlipy exposes itself as `brotli` but has no `__version__`; treat
    # any module we can't parse a version out of as (0, 0).
    try:
        parts = mod.__version__.split(".")[:2]  # type: ignore[attr-defined]
        return (int(parts[0]), int(parts[1]))
    except (AttributeError, ValueError, TypeError):
        return (0, 0)


@pytest.mark.skipif(not HAS_BROTLI, reason="brotli is not installed")
def test_system_brotli_is_module_of_record() -> None:
    from aiohttp.http_parser import _brotli

    assert _brotli is not None
    assert not _brotli.__name__.startswith("aiohttp._vendored")


@pytest.mark.skipif(not HAS_BROTLI, reason="brotli is not installed")
def test_brotli_decompressor_is_at_least_1_2() -> None:
    from aiohttp.http_parser import _brotli_decompressor

    assert _brotli_decompressor is not None
    assert _ver(_brotli_decompressor) >= (1, 2), _brotli_decompressor.__version__


@pytest.mark.skipif(not HAS_BROTLI, reason="brotli is not installed")
def test_brotli_bomb_is_capped() -> None:
    from aiohttp.http_parser import _brotli

    assert _brotli is not None
    original = b"A" * (64 * 2**20)
    compressed = _brotli.compress(original)
    assert len(compressed) < 2**16

    decompressor = BrotliDecompressor()
    out = decompressor.decompress(
        compressed, max_length=DEFAULT_MAX_DECOMPRESS_SIZE + 1
    )
    assert len(out) > DEFAULT_MAX_DECOMPRESS_SIZE
    assert len(out) < len(original)


@pytest.mark.skipif(
    _system_brotli is None or _ver(_system_brotli) >= (1, 2),
    reason="requires an OLD (<1.2) system brotli to prove the vendored fallback",
)
def test_old_system_brotli_uses_vendored_decompressor() -> None:
    from aiohttp.http_parser import _brotli, _brotli_decompressor

    assert _brotli is not None
    assert _brotli_decompressor is not None
    assert _system_brotli is not None

    assert _brotli is _system_brotli
    assert _brotli.__name__ == "brotli"
    assert _ver(_brotli) < (1, 2)

    assert _brotli_decompressor is not _system_brotli
    assert _brotli_decompressor.__name__.startswith("aiohttp._vendored")
    assert _ver(_brotli_decompressor) >= (1, 2)

    original = b"A" * (64 * 2**20)
    compressed = _brotli.compress(original)
    out = BrotliDecompressor().decompress(
        compressed, max_length=DEFAULT_MAX_DECOMPRESS_SIZE + 1
    )
    assert len(out) > DEFAULT_MAX_DECOMPRESS_SIZE
    # Old Google brotli's Decompressor exposes `.process(data, max_length)`
    # which rejects the kwarg as TypeError; brotlipy (also imports as
    # "brotli") has no `.process()` at all and raises AttributeError. Both
    # are valid evidence that the OLD system API can't enforce a cap on its
    # own, which is why we ship the vendored decompressor.
    with pytest.raises((TypeError, AttributeError)):
        _system_brotli.Decompressor().process(compressed, DEFAULT_MAX_DECOMPRESS_SIZE)


@pytest.mark.skipif(not HAS_BROTLI, reason="brotli is not installed")
def test_coexistence_subprocess_no_segfault() -> None:
    # Subprocess defends against `brotli.__version__` being absent (brotlipy
    # exposes itself as `brotli` without it) by treating that case as the
    # old API — same path the in-process code in http_parser.py takes.
    result = _run_py("""
        import importlib.util, sys
        if importlib.util.find_spec("brotli") is None:
            print("SKIP: no system brotli"); sys.exit(0)
        import brotli
        sysver = getattr(brotli, "__version__", None)
        from aiohttp.http_parser import (
            _brotli, _brotli_decompressor, HAS_BROTLI,
        )
        assert HAS_BROTLI is True
        assert _brotli is brotli
        assert "brotli" in sys.modules

        def _mm(mod):
            v = getattr(mod, "__version__", None)
            if v is None:
                return (0, 0)
            parts = v.split(".")[:2]
            return (int(parts[0]), int(parts[1]))

        sysmm = _mm(brotli)
        assert _brotli_decompressor is not None
        decmm = _mm(_brotli_decompressor)
        assert decmm >= (1, 2), decmm
        if sysmm >= (1, 2):
            assert _brotli_decompressor is brotli
        else:
            assert _brotli_decompressor is not brotli
            assert _brotli_decompressor.__name__.startswith("aiohttp._vendored")
            assert "aiohttp._vendored.brotli" in sys.modules

        data = brotli.compress(b"x" * 1000)
        assert brotli.decompress(data) == b"x" * 1000
        from aiohttp.http_parser import BrotliDecompressor
        BrotliDecompressor()
        print("OK system=%s decompressor=%s" % (
            sysver or "<no-__version__>",
            getattr(_brotli_decompressor, "__version__", "<no-__version__>"),
        ))
        """)
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout or "SKIP" in result.stdout, result.stdout


def test_no_system_brotli_disables_br_subprocess() -> None:
    # DeflateBuffer.__init__ raises ContentEncodingError BEFORE touching the
    # `out` stream when encoding='br' and brotli is absent, so we don't need
    # aiohttp.base_protocol.BaseProtocol (which was added after 3.0.8) — we
    # can pass `None` as the out stream.
    result = _run_py("""
        import sys, os
        class _Blocker:
            def find_spec(self, name, path=None, target=None):
                if name in ("brotli", "brotlicffi"):
                    raise ImportError("blocked for test")
                return None
        sys.meta_path.insert(0, _Blocker())
        for m in [k for k in sys.modules if k.split(".")[0] in ("brotli", "brotlicffi")]:
            del sys.modules[m]

        from aiohttp.http_parser import (
            HAS_BROTLI, _brotli, _brotli_decompressor,
        )
        assert HAS_BROTLI is False, "HAS_BROTLI should be False without system brotli"
        assert _brotli is None
        assert _brotli_decompressor is None

        import aiohttp
        vp = os.path.join(os.path.dirname(aiohttp.__file__), "_vendored", "brotli.py")
        assert os.path.exists(vp), "vendored brotli.py should still ship"

        from aiohttp.http_parser import DeflateBuffer
        from aiohttp.http_exceptions import ContentEncodingError
        try:
            DeflateBuffer(None, "br")
        except ContentEncodingError:
            print("OK br disabled, vendored still ships")
        else:
            raise AssertionError("DeflateBuffer(None, 'br') did not raise")
        """)
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout, result.stdout

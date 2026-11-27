# Dependencies

The tool uses established open-source libraries instead of custom code
wherever one fits. Everything outside the runtime list is optional or used only
by the documentation and tests.

## Runtime (`requirements.txt`)

| Project | Version | Used for | Source |
|---|---|---|---|
| Python | 3.12 or later | Runs `compare.py` | [python/cpython](https://github.com/python/cpython) · [python.org](https://www.python.org/) |
| NumPy | `>=1.26,<3` | Array maths, RMS, cents and dB calculations | [numpy/numpy](https://github.com/numpy/numpy) · [numpy.org](https://numpy.org/) |
| SciPy | `>=1.11,<2` | Autocorrelation and peak finding for pitch tracking (`scipy.signal`) | [scipy/scipy](https://github.com/scipy/scipy) · [scipy.org](https://scipy.org/) |
| soundfile | `>=0.13,<1` | Reading WAV, FLAC and OGG; writing listening copies (libsndfile, BSD-3-Clause) | [bastibe/python-soundfile](https://github.com/bastibe/python-soundfile) |
| pyloudnorm | `>=0.1.1,<1` | Integrated loudness (ITU-R BS.1770) for level-matched listening copies (MIT) | [csteinmetz1/pyloudnorm](https://github.com/csteinmetz1/pyloudnorm) |
| mir_eval | `>=0.8,<1` | Standard note-transcription match scores (MIT) | [mir-evaluation/mir_eval](https://github.com/mir-evaluation/mir_eval) |
| pretty_midi | `>=0.2.10,<1` | Writing `reference-notes.mid` (MIT) | [craffel/pretty-midi](https://github.com/craffel/pretty-midi) |

## Tests (`requirements-dev.txt`)

| Project | Version | Used for | Source |
|---|---|---|---|
| pytest | `>=8,<10` | Running the unit tests in `tests/` | [pytest-dev/pytest](https://github.com/pytest-dev/pytest) · [docs.pytest.org](https://docs.pytest.org/) |

## Documentation site

| Project | Version | Used for | Source |
|---|---|---|---|
| Zensical | `0.1.3` | Building this site from `docs/` | [zensical/zensical](https://github.com/zensical/zensical) · [zensical.org](https://zensical.org/) |

## Optional tools

| Project | Used for | Source |
|---|---|---|
| uv | Creating the virtual environment quickly | [astral-sh/uv](https://github.com/astral-sh/uv) · [docs.astral.sh/uv](https://docs.astral.sh/uv/) |
| Git for Windows | Cloning the repository | [git-for-windows/git](https://github.com/git-for-windows/git) · [git-scm.com](https://git-scm.com/) |
| Dorico | Producing the audio export. It is **not** needed to run the tool. | [steinberg.net/dorico](https://www.steinberg.net/dorico/) (closed source) |

## GitHub Actions used by CI

| Action | Workflow | Source |
|---|---|---|
| `actions/checkout` | Tests, Documentation | [actions/checkout](https://github.com/actions/checkout) |
| `actions/setup-python` | Tests, Documentation | [actions/setup-python](https://github.com/actions/setup-python) |
| `actions/configure-pages` | Documentation | [actions/configure-pages](https://github.com/actions/configure-pages) |
| `actions/upload-pages-artifact` | Documentation | [actions/upload-pages-artifact](https://github.com/actions/upload-pages-artifact) |
| `actions/deploy-pages` | Documentation | [actions/deploy-pages](https://github.com/actions/deploy-pages) |

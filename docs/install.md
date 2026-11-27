# Install on Windows

You need **Python 3.12 or later**. The README uses
[uv](https://docs.astral.sh/uv/) to create the virtual environment, but the
standard `venv` module works too.

## 1. Get the code

Clone the repository, or download it as a ZIP from GitHub and extract it:

```powershell
git clone https://github.com/AndyW98/music-ai.git
cd music-ai
```

## 2. Create the environment

=== "uv (recommended)"

    ```powershell
    uv venv .venv
    uv pip install --python .venv\Scripts\python.exe -r requirements.txt
    ```

=== "Standard venv"

    ```powershell
    py -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    ```

This installs the dependencies (NumPy, SciPy, soundfile, pyloudnorm, mir_eval
and pretty_midi) into `.venv` inside the project folder. See
[Dependencies](dependencies.md) for what each one does.

## 3. Check it works

```powershell
.\.venv\Scripts\python.exe compare.py --help
```

You should see the usage line and the list of options.

## What stays on your machine

The repository's `.gitignore` excludes the virtual environment (`.venv/`),
the analysis cache (`work/`), the reports (`outputs/`) and all `*.wav`,
`*.ogg`, `*.flac` and `*.dorico` files. Recordings, projects and reports therefore
stay out of Git unless you add them on purpose.

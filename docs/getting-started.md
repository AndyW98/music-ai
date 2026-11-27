# First-time setup guide

This guide starts from a Windows PC with nothing installed and ends with your
first comparison report. It takes about 15 minutes. You do **not** need Dorico
on the PC that runs the comparison, only the WAV file exported from it.

## Step 1: Install Python

1. Download and install Python 3.10 or later for Windows from
   [python.org/downloads](https://www.python.org/downloads/). Follow the
   installer's instructions. If it offers an option to add Python to `PATH`,
   turn it on.
2. Close any open PowerShell windows so the new install is picked up.
3. Open **PowerShell** and check that it worked:

    ```powershell
    py --version    # or: python --version
    ```

## Step 2: Install uv (optional but recommended)

[uv](https://docs.astral.sh/uv/) creates the project's Python environment
quickly. The [uv README](https://github.com/astral-sh/uv) gives this
Windows install command:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Close and reopen PowerShell afterwards. See the
[uv installation page](https://docs.astral.sh/uv/getting-started/installation/)
for other methods. If you would rather not install uv, use the
**Standard venv** tab in Step 4.

## Step 3: Get the code

=== "With Git"

    Install [Git for Windows](https://git-scm.com/download/win), then:

    ```powershell
    git clone https://github.com/AndyW98/music-ai.git
    cd music-ai
    ```

=== "Without Git"

    1. Open <https://github.com/AndyW98/music-ai>.
    2. Click **Code → Download ZIP** and extract it.
    3. In PowerShell, `cd` into the extracted folder.

## Step 4: Create the environment

=== "uv"

    ```powershell
    uv venv .venv
    uv pip install --python .venv\Scripts\python.exe -r requirements.txt
    ```

=== "Standard venv"

    ```powershell
    py -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    ```

This installs [NumPy](https://github.com/numpy/numpy) and
[SciPy](https://github.com/scipy/scipy) into the `.venv` folder. Nothing is
installed system-wide.

## Step 5: Try it on the sample audio

The repository can generate a pair of synthetic WAV files whose differences are
known, so you can see what a report looks like before using real recordings:

```powershell
.\.venv\Scripts\python.exe tests\sample_audio.py samples
.\.venv\Scripts\python.exe compare.py samples\reference.wav samples\render.wav
```

The second command prints a path such as
`outputs\comparison-ab12cd34\comparison.md`. Open it in any text editor or
Markdown viewer. You should see three matched notes. Two of them are altered:

| What was changed in the render | Expected in the report |
|---|---|
| Note 2: 25 cents sharp, 40 ms late, 50 ms longer | about +25 cents, +40 ms attack, +50 ms duration |
| Note 3: 18 cents flat, 30 ms early, 40 ms shorter | about −18 cents, −30 ms attack, −40 ms duration |
| Whole file starts 0.2 s later | offset about +0.200 s |

Timings can differ by up to 10 ms, because the analysis works in 10 ms steps.

## Step 6: Export audio from Dorico

On the computer with Dorico, export the phrase you want to check as **WAV**
from Dorico's **Export Audio** dialog. Steinberg's
[Exporting the audio guide](https://steinberg.help/dorico_first_steps/v5/en/dorico_first_steps/topics/first_steps_print_export/first_steps_audio_exporting_t.html)
shows how to open the dialog in your version. Tips:

- Choose **WAV**. Any bit depth works.
- Export only the solo instrument, so that one note sounds at a time.
- Copy the WAV to the PC that runs the comparison. The tool only reads it.

## Step 7: Compare your recording

Put your solo recording (WAV) and the Dorico export somewhere convenient. They
do not need to be inside the project folder. Then run:

```powershell
.\.venv\Scripts\python.exe compare.py "C:\Music\my-take.wav" "C:\Music\dorico-export.wav"
```

If the phrase starts at a different time in each file, select it with
time ranges in seconds:

```powershell
.\.venv\Scripts\python.exe compare.py "C:\Music\my-take.wav" "C:\Music\dorico-export.wav" `
  --reference-start 1.2 --reference-end 9 --render-end 8.4
```

Next, read [Read the report](report.md) to understand the numbers, and
[Run a comparison](usage.md) for every option.

## Optional: run the tests

To check that everything works on your machine:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
```

If you used uv, replace the first line with
`uv pip install --python .venv\Scripts\python.exe -r requirements-dev.txt`.
All tests should pass.

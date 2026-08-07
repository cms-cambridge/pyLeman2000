# Setting up a MATLAB Compiler host

Notes from bringing up R2026a + Compiler on a remote Linux box (musix) from a
Mac, so the next person does not have to rediscover the same traps. Once the
host is ready, build with `./scripts/build_matlab_image.sh` (see
[README.md](README.md)).

## Why a remote Linux box

- MATLAB Compiler packages **linux/amd64** Runtime images. Building on Apple
  Silicon / macOS does not give you that artifact.
- GitHub-hosted runners cannot hold a MathWorks Compiler license. Use a machine
  you control (departmental server, VM, etc.).
- After the image is published to GHCR, end users only need Docker — no MATLAB
  install.

## Remote desktop from a Mac

MATLAB’s installer wants a GUI. Plain SSH is not enough unless you already have
a silent installer input file and are comfortable with that path.

### What worked: TigerVNC + XFCE

On the Linux host (Ubuntu-ish):

```bash
sudo apt-get update
sudo apt-get install -y tigervnc-standalone-server xfce4 xfce4-goodies
```

Start a VNC session as your normal user (not root):

```bash
vncserver :1 -geometry 1920x1080 -depth 24
# first run asks for a VNC password
```

`~/.vnc/xstartup` should launch XFCE, for example:

```bash
#!/bin/sh
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
exec startxfce4
```

From the Mac, tunnel and connect:

```bash
ssh -L 5901:localhost:5901 USER@HOST
```

Then open **Screen Sharing** (or RealVNC / TigerVNC Viewer) to `localhost:5901`.

### What did not work well: xrdp

Microsoft Remote Desktop / Windows App on Mac often sat on “Configuring remote
PC”. Logs showed `xrdp-sesman` restarting without completing a session. If you
retry xrdp later:

- Ensure `/etc/xrdp/key.pem` is readable by the xrdp user
  (`chown root:ssl-cert`, `chmod 640`, `adduser xrdp ssl-cert`).
- Prefer VNC for one-off installer work; it is simpler to debug over SSH.

### Display / sudo notes

- `sudo` may still ask for a password even when you are in the `sudo` group.
- Running a GUI installer under `sudo` needs the X/VNC display allowed for root
  (`xhost +SI:localuser:root` in the desktop session) — usually better to
  install MATLAB into your home directory as yourself when policy allows.

## Installing MATLAB

Cambridge’s documented flow (adapt license labels for your site):

1. Run the installer.
2. Sign in with a MathWorks account.
3. Choose **Academic – Total Headcount – Individual** (or your site’s
   equivalent).
4. Select products — for this project you need at least **MATLAB** and
   **MATLAB Compiler**. Compiler SDK is useful if you later package libraries /
   microservices, but the standalone worker only needs Compiler.
5. At first launch, sign in again if prompted.

### Avoid relying on a browser on the server

Snap Chromium failed here with `chromium: not a snap cgroup`. Reliable path:

1. On the Mac, download the Linux MATLAB installer from MathWorks.
2. Copy it over: `scp matlab_R2026a_glnxa64.zip USER@HOST:~/`
3. Unzip on the host and run the installer **inside the VNC desktop**.

### Username / home-directory traps

- MathWorks tooling can choke on usernames containing `@` (common with
  institutional SSO-style accounts). Prefer a host account whose `$HOME` and
  login name are plain UNIX identifiers.
- Installing under `$HOME/MATLAB/R2026a` avoids needing write access to
  `/usr/local/MATLAB` when you do not have (or do not want) a root install.

### Verify Compiler after install

```bash
export MATLAB_ROOT=$HOME/MATLAB/R2026a   # or your install path
"$MATLAB_ROOT/bin/matlab" -batch "disp(version)"
"$MATLAB_ROOT/bin/mcc" -?
```

`license('test','MATLAB_Compiler')` may return `0` even when `mcc` works. Trust
a tiny `mcc -m` hello-world more than the license feature flag.

## After MATLAB is installed

```bash
git clone git@github.com:cms-cambridge/pyLeman2000.git
cd pyLeman2000
./scripts/build_matlab_image.sh --tag dev
# optional: docker login ghcr.io && ./scripts/build_matlab_image.sh --tag dev --push
```

The build script handles IPEM pin, mex, `mcc`, custom Runtime image, packaging,
and a license-free smoke test.

## Quirks discovered while compiling this app

Worth remembering if something breaks again:

| Symptom | Cause / fix |
| --- | --- |
| `Unrecognized function or variable 'savepath'` in deployed app | `IPEMSetup` called `path2rc`; skip when `isdeployed` (IPEMToolbox PR #3). |
| `warning` errors in `IPEMContextualityIndex` on R2026a | Old `[ws,wf]=warning` API; use `warning('query')` / restore (PR #2). |
| `wavread` / `wavwrite` missing | Put fork `OctaveCompat` shims on the path (MATLAB and Octave). |
| Huge JSON for `detail=0` | Standalone apps pass args as text; `detail > 1` was true for `'0'`. Parse numerics in `leman_2000_compute`. |
| Official Runtime image ~7.7 GB | Use `compiler.runtime.createDockerImage` with `OptionalDependencies=none` (~3.8 GB for this app). |
| Confirm no license at runtime | Set `MLM_LICENSE_FILE` to a nonexistent path and `AGREE_TO_MATLAB_RUNTIME_LICENSE=yes`. |

## SSH-only checklist (once GUI install is done)

```bash
hostname; whoami
echo "MATLAB_ROOT=${MATLAB_ROOT:-$HOME/MATLAB/R2026a}"
test -x "${MATLAB_ROOT:-$HOME/MATLAB/R2026a}/bin/mcc" && echo "mcc ok"
docker info >/dev/null && echo "docker ok"
git --version; gcc --version | head -1
```

No VNC needed for rebuilds after the first successful Compiler install.

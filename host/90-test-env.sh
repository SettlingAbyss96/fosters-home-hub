#!/usr/bin/env bash
# A test bench for the house's logic: Home Assistant itself (the same version as the VM, 2026.10.0)
# in a virtual environment on the Hub, so tests/ can load the real packages, freeze the clock at
# 4:55 on a Tuesday and watch what the automations actually do. Not a copy of the template engine,
# the real one. tools/test.sh runs it, and tools/ha-apps.sh won't deploy if it fails.
# Home Assistant 2026.10 wants Python 3.14 and Debian has 3.13, so uv brings its own 3.14 along.
# Pinned: uv by version, the test package by version (it pins Home Assistant exactly).
# From the PC: tools/push.sh host/90-test-env.sh
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
user=hub
home=$(getent passwd "$user" | cut -d: -f6)
dir=$home/ha-test
as_user() { sudo -u "$user" "$@"; }

apt-get install -y -qq --no-install-recommends python3-venv >/dev/null
install -d -o "$user" -g "$user" "$dir"
[ -x "$dir/uv/bin/uv" ] || { as_user python3 -m venv "$dir/uv" && as_user "$dir/uv/bin/pip" install -q --disable-pip-version-check uv==0.12.19; }
uv=$dir/uv/bin/uv
export UV_PYTHON_INSTALL_DIR=$dir/python UV_CACHE_DIR=$dir/cache
as_user env UV_PYTHON_INSTALL_DIR="$UV_PYTHON_INSTALL_DIR" "$uv" python install -q 3.14
[ -x "$dir/venv/bin/python" ] || as_user env UV_PYTHON_INSTALL_DIR="$UV_PYTHON_INSTALL_DIR" "$uv" venv -q --python 3.14 "$dir/venv"
as_user env UV_CACHE_DIR="$UV_CACHE_DIR" VIRTUAL_ENV="$dir/venv" "$uv" pip install -q \
  pytest-homeassistant-custom-component==0.13.371
as_user "$dir/venv/bin/python" -c "import homeassistant.const as c; print('test bench: Home Assistant', c.__version__)"

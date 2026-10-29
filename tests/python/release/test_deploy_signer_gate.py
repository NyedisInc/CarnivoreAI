
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEPLOY = ROOT / "scripts" / "deploy-dmg.sh"
TEXT = DEPLOY.read_text()

DEV = 'identifier "ai.carnivore.menubar" and certificate root = H"aaaa"'


def _func(name: str) -> str:
    start = TEXT.index(f"{name}() {{")
    return TEXT[start : TEXT.index("\n}\n", start) + 3]


def _gate(installed: str, satisfies: list[str], allow: int) -> subprocess.CompletedProcess:
    sat = "\n".join(satisfies)
    script = f"""
log() {{ echo "$*"; }}
APP=/nonexistent/Carnivore.app
{_line("REQ")}
{_line("DEVID_REQ")}
ALLOW_SIGNER_CHANGE={allow}
PIN_REQ=""
INSTALLED='{installed}'
SATISFIES='{sat}'
codesign() {{
  if [ "$1" = -d ]; then echo "designated => $INSTALLED"; return 0; fi
  local want="${{2#-R=}}"
  printf '%s\\n' "$SATISFIES" | grep -qxF -- "$want"
}}
{_func("installed_requirement")}
{_func("choose_signature_requirement")}
choose_signature_requirement /x/new.app
echo "PIN=$PIN_REQ"
"""
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True)


def _line(var: str) -> str:
    return next(l for l in TEXT.splitlines() if l.startswith(f"{var}="))


def _devid() -> str:
    return _line("DEVID_REQ").split("=", 1)[1].strip("'")


def test_same_signer_as_installed_passes_and_pins_the_installed_requirement():
    out = _gate(DEV, [DEV], 0)
    assert out.returncode == 0 and f"PIN={DEV}" in out.stdout


def test_developer_id_dmg_over_a_dev_signed_app_is_refused_with_the_fda_message():
    out = _gate(DEV, [_devid()], 0)
    assert out.returncode == 2
    assert "Full Disk Access" in out.stdout and "--allow-signer-change" in out.stdout


def test_signer_change_is_accepted_only_with_the_flag_and_warns_about_regrant():
    out = _gate(DEV, [_devid()], 1)
    assert out.returncode == 0 and f"PIN={_devid()}" in out.stdout
    assert "do NOT carry over" in out.stdout


def test_developer_id_to_developer_id_needs_no_flag():
    installed = _devid() + " and certificate 1[field.1.2.840.113635.100.6.2.6] /* exists */"
    assert _gate(installed, [installed], 0).returncode == 0


def test_unknown_signer_is_refused_even_with_the_flag():
    out = _gate(DEV, ["identifier \"other\""], 1)
    assert out.returncode == 2 and "refusing" in out.stdout


def test_unreadable_installed_requirement_still_refuses_a_foreign_signer():
    assert _gate("", ["identifier \"other\""], 0).returncode == 2


def test_backup_dir_falls_back_to_a_local_folder_without_the_usb_volume():
    block = TEXT[TEXT.index('if [ -z "$BACKUP_ROOT" ]; then') : TEXT.index('BACKUP_DIR="$BACKUP_ROOT')]
    assert "/Volumes/Backup" in block and "Carnivore-predeploy-backups" in block
    script = f'HOME=/h\nBACKUP_ROOT=/explicit\n{block}\necho "$BACKUP_ROOT"'
    assert subprocess.run(["bash", "-c", script], capture_output=True, text=True).stdout.strip() == "/explicit"
    script = f'HOME=/h\nBACKUP_ROOT=""\n{block.replace("/Volumes/Backup ]", "/nonexistent-vol ]")}\necho "$BACKUP_ROOT"'
    got = subprocess.run(["bash", "-c", script], capture_output=True, text=True).stdout.strip()
    assert got == "/h/Library/Application Support/Carnivore-predeploy-backups"


def test_missing_releases_dir_refuses_before_touching_anything(tmp_path):
    out = subprocess.run(
        [str(DEPLOY), "9.9.9", "--releases-dir", str(tmp_path / "absent")], capture_output=True, text=True
    )
    assert out.returncode == 2 and "does not exist" in out.stdout

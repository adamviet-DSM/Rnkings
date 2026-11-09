"""One-time helper: write the service account JSON into .env correctly."""
import json, re, sys
from pathlib import Path

if len(sys.argv) < 2:
    print("Usage: python3 scripts/fix_env.py /path/to/service-account-key.json")
    sys.exit(1)

key_path = Path(sys.argv[1])
if not key_path.exists():
    print(f"ERROR: file not found: {key_path}")
    sys.exit(1)

with open(key_path) as f:
    data = json.load(f)

val = json.dumps(data)
env_path = Path(__file__).parent.parent / ".env"
env = env_path.read_text()

if "GOOGLE_SERVICE_ACCOUNT_JSON=" in env:
    env = re.sub(
        r"GOOGLE_SERVICE_ACCOUNT_JSON='[^']*'",
        f"GOOGLE_SERVICE_ACCOUNT_JSON='{val}'",
        env,
    )
    if "GOOGLE_SERVICE_ACCOUNT_JSON=" in env and f"'{val}'" not in env:
        # fallback: replace the whole line
        env = re.sub(r"GOOGLE_SERVICE_ACCOUNT_JSON=.*\n", f"GOOGLE_SERVICE_ACCOUNT_JSON='{val}'\n", env)
else:
    env += f"\nGOOGLE_SERVICE_ACCOUNT_JSON='{val}'\n"

env_path.write_text(env)
print(f"✓ Updated .env with credentials from {key_path.name}")
print(f"  Project: {data.get('project_id', '?')}")
print(f"  Account: {data.get('client_email', '?')}")

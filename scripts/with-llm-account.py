"""Select an explicitly authorized shared account without logging its credential."""
import os
import sys
from pathlib import Path


def main():
    if len(sys.argv) < 4 or sys.argv[1] not in ('tokenhub-secondary', 'ark-secondary'):
        raise SystemExit('Usage: with-llm-account.py ACCOUNT COMMAND [ARG ...]')
    account = sys.argv[1]
    ark = account == 'ark-secondary'
    path = Path('/home/ubuntu/.config/llm') / ('volcengine.env' if ark else 'tencent.env')
    values = {}
    for line in path.read_text().splitlines():
        name, sep, value = line.partition('=')
        if sep and not line.startswith('#'):
            values[name.strip()] = value.strip()
    name = 'ARK_API_KEY' if ark else 'TENCENT_API_KEY'
    value = values.get(name + '_2')
    if not value:
        raise SystemExit('The requested shared account is unavailable.')
    os.environ[name] = value
    if not ark:
        os.environ['TOKENHUB_API_KEY'] = value
        os.environ['TENCENT_BASE_URL'] = values['TENCENT_BASE_URL']
    os.environ['AGENT_MEMORY_LLM_ACCOUNT'] = account
    os.execvp(sys.argv[2], sys.argv[2:])


if __name__ == '__main__':
    main()

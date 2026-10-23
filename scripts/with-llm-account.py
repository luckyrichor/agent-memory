"""Select an explicitly authorized shared account without logging its credential."""
import os
import sys
from pathlib import Path


def main():
    from b0_accounts import ACCOUNTS, credential
    if len(sys.argv) < 4 or sys.argv[1] not in ACCOUNTS:
        raise SystemExit('Usage: with-llm-account.py ACCOUNT COMMAND [ARG ...]')
    account=sys.argv[1];provider,base,value=credential(account)
    ark=provider=='Ark';name='ARK_API_KEY' if ark else 'TENCENT_API_KEY'
    os.environ[name]=value
    os.environ['AGENT_MEMORY_ARK_ACCOUNT' if ark else 'AGENT_MEMORY_TOKENHUB_ACCOUNT']=account
    if not ark:
        os.environ['TOKENHUB_API_KEY']=value
        os.environ['TENCENT_BASE_URL']=base
    os.environ['AGENT_MEMORY_LLM_ACCOUNT']=account
    os.execvp(sys.argv[2], sys.argv[2:])


if __name__ == '__main__':
    main()

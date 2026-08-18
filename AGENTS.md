# AGENTS.md

## Git Push

Pushing to this repository requires the KonstantinosZornes SSH key:

```bash
GIT_SSH_COMMAND='ssh -i /home/wang/.ssh/id_ed25519.KonstantinosZornes -o IdentitiesOnly=yes' git push origin dev
```

Do not use the MarvekG key for `git@github.com:KonstantinosZornes/gpt-outlook-register.git`; it does not have write permission.

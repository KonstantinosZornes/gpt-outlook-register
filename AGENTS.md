# Agent notes

## Git push

本仓库 origin 为 `KonstantinosZornes/gpt-outlook-register`。默认 SSH 身份是 MarvekG，无写权限。推送时使用：

```bash
GIT_SSH_COMMAND='ssh -i ~/.ssh/id_ed25519.KonstantinosZornes -o IdentitiesOnly=yes' git push origin main
```

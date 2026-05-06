# whatsapp-agent-base — Instrucciones para Claude Code

> Template base reusable para agentes de WhatsApp. Este archivo guía a Claude Code
> al trabajar en este repo. Mantiene paridad con `whatsapp-agentkit/simpleprop-sofi`.

---

## Versionado del agente — bump rule

`agent/__init__.py` mantiene `__version__ = "X.Y.Z"` siguiendo SemVer.

Antes de cada commit que toque código del agente:

1. Leer `__version__` actual.
2. Bump según prefijo del commit:
   - `feat:` → minor
   - `fix:` → patch
   - `feat!:` o `BREAKING CHANGE:` → major
   - `docs:`, `chore:`, `style:`, `refactor:`, `test:`, `build:`, `ci:` → sin bump
3. Editar `agent/__init__.py` con la versión nueva.
4. `git add agent/__init__.py` + cambios → commit único.

Sync con `whatsapp-agentkit/simpleprop-sofi` con la misma versión final.

Si Claude se olvida del prefijo, no bumpea. Próximo commit con `feat:`/`fix:` retoma.

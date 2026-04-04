# WhatsApp Agent Base — Guía de setup por cliente

Pasos para configurar un nuevo agente desde este template.

## 1. Clonar y preparar

```bash
git clone https://github.com/biopaul/whatsapp-agent-base.git nombre-cliente
cd nombre-cliente
pip install -r requirements.txt
cp .env.example .env
```

## 2. Completar la información del cliente

**`config/business.yaml`** — datos del negocio

**`config/prompts.yaml`** — system prompt personalizado:
- Reemplazar todos los `[PLACEHOLDERS]` con la info del cliente
- Incorporar el contenido de `/knowledge` en la sección correspondiente

**`knowledge/`** — subir archivos del cliente (PDF, TXT, MD, CSV)

**`.env`** — completar con las API keys del cliente

## 3. Probar localmente

```bash
python tests/test_local.py
```

## 4. Deploy en Railway

```bash
git init
git add .
git commit -m "feat: agente [NOMBRE CLIENTE]"
gh repo create [nombre-repo] --private --source=. --remote=origin --push
```

Luego en Railway:
- New Project → Deploy from GitHub
- Agregar variables de entorno (ver `.env.example`)
- Generar dominio público (Settings → Networking)
- Configurar webhook en Whapi/Meta/Twilio con la URL generada

## Variables de entorno en Railway

| Variable | Valor |
|----------|-------|
| `ANTHROPIC_API_KEY` | key del cliente o compartida |
| `WHATSAPP_PROVIDER` | `whapi` / `meta` / `twilio` |
| `WHAPI_TOKEN` | token del canal Whapi |
| `PORT` | `8000` |
| `ENVIRONMENT` | `production` |

## Webhook Whapi

URL: `https://[dominio-railway]/webhook`
Modo: Method → activar `messages.post`

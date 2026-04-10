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

Responder estas preguntas antes de tocar cualquier archivo:

---

**¿Cuál es el nombre del negocio y a qué se dedica?**
Describir qué ofrece, a quién va dirigido y cómo funciona. Cuanto más detalle, mejor va a responder el agente.

---

**¿Cómo se llama el agente y cuál es su tono de comunicación?**
Nombre del personaje (ej: Sofi, Mateo, Luna) y descripción del tono (ej: cercano y profesional con voseo rioplatense / formal y técnico / amigable e informal).

---

**¿Cuál es la función principal del agente?**
Elegir la que mejor describe su rol o indicar una combinación:

| Función | Descripción |
|---------|-------------|
| `ventas` | Captar leads, presentar el producto/servicio y guiar al cliente hacia el cierre |
| `soporte` | Resolver dudas técnicas y ayudar con el uso del producto o servicio |
| `atencion_cliente` | Responder consultas generales y brindar información del negocio |
| `post_venta` | Dar seguimiento, fidelizar clientes y gestionar renovaciones |
| `reservas` | Gestionar agendas, citas o turnos |
| `cobranzas` | Enviar recordatorios de pago y gestionar vencimientos |
| `onboarding` | Dar la bienvenida y guiar a nuevos clientes en sus primeros pasos |
| `mixto` | Combinación de varias funciones — indicar cuáles y en qué orden de prioridad |

---

**¿El agente atiende las 24 horas los 7 días de la semana, o tiene un horario específico?**
- Si atiende **24/7**: no es necesario configurar nada más en esta sección.
- Si tiene **horario específico**: indicar los días de atención, la hora de inicio, la hora de cierre, la zona horaria y el mensaje exacto que debe enviar el agente cuando alguien escribe fuera de ese horario.
  - Ejemplo: *"Lunes a viernes de 9:00 a 18:00 (GMT-3). Fuera de horario: 'Hola, en este momento no estoy disponible. Te respondo el próximo día hábil en horario de atención. ¡Gracias!'"*

---

**¿Qué número debe recibir las alertas cuando el agente necesita derivar a un humano?**
Formato internacional sin `+` (ej: `5491155554444`). Opcionalmente, indicar el nombre de la persona para personalizar los mensajes.

---

Con esas respuestas, completar:

**`config/business.yaml`** — datos estructurados del negocio y configuración de horario

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
| `NOTIFY_PHONE` | número que recibe alertas de escalado (sin `+`, ej: `5491155554444`) |
| `NOTIFY_NAME` | nombre de la persona que recibe las alertas (ej: `Nani`) |
| `PORT` | `8000` |
| `ENVIRONMENT` | `production` |

## Webhook Whapi

URL: `https://[dominio-railway]/webhook`
Modo: Method → activar `messages.post`

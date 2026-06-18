# Setup Multi-Website + Subdominio por Tenant

Esta guía explica cómo configurar la infraestructura para que `cliente1.innatum.com`, `cliente2.innatum.com`, etc., apunten al mismo servidor Odoo pero a websites distintos, cada uno con su propia `res.company` (tenant).

## Arquitectura

```
DNS wildcard          Reverse proxy (Nginx)        Odoo
*.innatum.com  ──►   recibe Host header  ──►   request.website
   │                  pasa al backend                 │
   ▼                                                  ▼
clienteX.innatum.com                            company_id del website
                                                = tenant
```

## Módulos a instalar (3 packs)

Hay 3 módulos "meta" que agrupan instalaciones según el caso de uso. Instalalos
según necesidad:

| Pack | Qué instala | Para qué |
|---|---|---|
| `innatum_basico` | core + planes + web | SaaS de agendamiento mínimo (sin IA, sin facturación) — **siempre obligatorio** |
| `innatum_ia` | innatum_basico + ai + ai_web | Suma chatbot IA con gate por suscripción |
| `innatum_contable` | innatum_basico + facturacion | Suma facturación EC (l10n_ec_edi, solo tenants Ecuador) |

### Comandos de instalación

```bash
# Mínima (solo agendamiento)
docker exec <contenedor_odoo> odoo -d <bd> -i innatum_basico --stop-after-init --no-http

# Con IA
docker exec <contenedor_odoo> odoo -d <bd> -i innatum_basico,innatum_ia --stop-after-init --no-http

# Con IA + contabilidad EC
docker exec <contenedor_odoo> odoo -d <bd> -i innatum_basico,innatum_ia,innatum_contable --stop-after-init --no-http
```

Cada pack arrastra sus dependencias automáticamente.

Cada subdominio mapea a un `website` con su `domain` y su `company_id`. Toda la lógica de aislamiento se basa en `request.website.company_id` — ver [project_saas_in_agendamiento_arquitectura](../../../../.claude/projects/-home-saquito-proyecto/memory/project_saas_in_agendamiento_arquitectura.md).

---

## 1. DNS

Configurar un registro **wildcard A** apuntando al IP del servidor:

```
*.innatum.com.    300    IN    A    <IP_SERVER>
innatum.com.      300    IN    A    <IP_SERVER>
```

Verificar:
```bash
dig +short cliente1.innatum.com
dig +short cliente2.innatum.com
# Ambos deben devolver el mismo IP
```

---

## 2. SSL wildcard (Let's Encrypt DNS-01)

HTTP-01 challenge **no soporta wildcards**, hay que usar DNS-01. Si tu DNS es Cloudflare:

```bash
sudo apt install certbot python3-certbot-dns-cloudflare
sudo mkdir -p /etc/letsencrypt/cloudflare
sudo tee /etc/letsencrypt/cloudflare/credentials.ini <<EOF
dns_cloudflare_api_token = <TU_API_TOKEN_CLOUDFLARE>
EOF
sudo chmod 600 /etc/letsencrypt/cloudflare/credentials.ini

sudo certbot certonly \
  --dns-cloudflare \
  --dns-cloudflare-credentials /etc/letsencrypt/cloudflare/credentials.ini \
  -d "innatum.com" -d "*.innatum.com" \
  --agree-tos -m admin@innatum.com -n
```

Renovación automática:
```bash
sudo systemctl enable certbot.timer
```

Para otros DNS providers (Route53, DigitalOcean, etc.): cambiar `dns-cloudflare` por el plugin correspondiente.

---

## 3. Nginx reverse proxy

`/etc/nginx/sites-available/innatum`:

```nginx
upstream odoo {
    server 127.0.0.1:8069;
}

upstream odoo_longpolling {
    server 127.0.0.1:8072;
}

# Redirect HTTP → HTTPS
server {
    listen 80;
    server_name innatum.com *.innatum.com;
    return 301 https://$host$request_uri;
}

# HTTPS server — cubre el dominio raíz y todos los subdominios
server {
    listen 443 ssl http2;
    server_name innatum.com *.innatum.com;

    ssl_certificate     /etc/letsencrypt/live/innatum.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/innatum.com/privkey.pem;

    # Pasar el Host header al backend — CRÍTICO para que
    # request.httprequest.host coincida con website.domain
    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_redirect   off;

    client_max_body_size 50M;

    location /websocket {
        proxy_pass http://odoo_longpolling;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    location / {
        proxy_pass http://odoo;
    }

    location ~* /web/static/ {
        proxy_pass http://odoo;
        proxy_cache_valid 200 60m;
        expires 864000;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/innatum /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

---

## 4. Configuración Odoo

En `odoo.conf`:

```ini
proxy_mode = True
list_db = False
```

`proxy_mode = True` es **obligatorio** para que Odoo respete `X-Forwarded-Proto` y devuelva URLs https correctas.

Reiniciar Odoo después del cambio.

---

## 5. Crear un tenant nuevo (manual, mientras no exista el wizard)

Hasta que se implemente la Fase 3 con `innatum_agenda_planes.wizard_provisioning`, los pasos manuales son:

### 5.1 Crear la company
1. Settings → Companies → Companies → **Create**
2. Campos:
   - Name: `Peluquería Estilo Lima`
   - Email, dirección, etc.
   - **Timezone**: el del cliente (se usa para generar slots — ver [config.py:228](../innatum_agenda_core/models/innatum_agenda_config.py#L228))

### 5.2 Crear el website
1. Website → Configuration → Websites → **New**
2. Campos:
   - Website Name: `Peluquería Estilo`
   - **Domain**: `https://estilo.innatum.com` (sin trailing slash, con protocolo)
   - **Company**: la company del paso 5.1 ⚠️ **crítico** — esta es la llave maestra del aislamiento
   - Language: ES

### 5.3 Crear admin user del tenant
1. Settings → Users → Users → **Create**
2. Campos:
   - Login: `admin@estilo.innatum.com`
   - **Allowed Companies**: solo la company del tenant (quitar la principal)
   - **Default Company**: la del tenant
   - Access Rights:
     - **Innatum Agenda → Administrador** (innatum_agenda_group_admin)
     - Si va a usar IA: **AI Assistant → Usuario IA**
3. Set password via "Send Invitation Email" o desde el form.

### 5.4 Datos iniciales del tenant
Loguearse como el admin del tenant (no como Innatum admin) y crear:
1. Servicios (`Agenda → Servicios`)
2. Empleados profesionales (`Personal`)
3. Planificación de horarios (`Agenda → Horarios`) → aprobar para generar turnos

### 5.5 Verificar aislamiento
Abrir `https://estilo.innatum.com` en navegador anónimo:
- Debe mostrar solo profesionales/servicios de Peluquería Estilo
- Repetir con `https://otrotenant.innatum.com` → debe mostrar solo los suyos
- Inspeccionar `request.website.id` y `request.website.company_id` desde una vista en debug si hay dudas

---

## 6. Troubleshooting

| Síntoma | Causa probable | Fix |
|---|---|---|
| `cliente1.innatum.com` muestra el website default (no el del tenant) | `domain` del website no coincide con el host visitado | Editar `website.domain` que sea exacto: `https://cliente1.innatum.com` |
| Logo del tenant aparece en otro tenant | Logo fue subido al website default; cada tenant tiene su propio website y debe subir su propio logo | Subir logo en cada `website.logo` |
| HTTPS redirects loop | Falta `proxy_mode=True` en odoo.conf, o nginx no pasa `X-Forwarded-Proto` | Verificar ambos |
| `/citas/submit` devuelve "horario ya no disponible" cuando el turno SÍ existe | El turno pertenece a otra company (`turno.company_id != request.website.company_id`). El controller lo bloquea correctamente. | Confirmar que el visitante está en el website correcto |
| Chatbot crea sesiones cross-company | `request.website.company_id` no está seteado | Asegurarse de que `website.company_id` esté lleno y el visitante venga por subdomain correcto |
| Certbot falla con "wildcard requires DNS challenge" | Estás usando HTTP-01 challenge | Cambiar a DNS-01 — ver sección 2 |

---

## 7. Notas para Fase 3

Cuando se implemente `innatum_agenda_planes`, el wizard `action_provision_tenant()` debe automatizar pasos 5.1, 5.2, 5.3 en una sola transacción + crear `in_agenda.suscripcion`. Ver [project_saas_in_agendamiento_arquitectura](../../../../.claude/projects/-home-saquito-proyecto/memory/project_saas_in_agendamiento_arquitectura.md).

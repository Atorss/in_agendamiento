# Configuración de Subdominio para Nuevo Tenant

Este documento describe el procedimiento completo para configurar un nuevo subdominio cuando se crea un tenant en la plataforma de agendamiento.

## Arquitectura

```
┌─────────────────────────────────────────────────────────────┐
│  NGINX PROXY MANAGER (NPM)                                  │
│  ├─ Contenedor: nginx-proxy-manager                         │
│  ├─ Base de datos: proxy-db (PostgreSQL)                    │
│  ├─ Panel web: http://[servidor]:81                         │
│  └─ Credenciales: admin@admin.com / ##Xtreme12              │
└─────────────────────────────────────────────────────────────┘
          │
          │ (proxy reverso)
          ▼
┌─────────────────────────────────────────────────────────────┐
│  ODOO AGENDAMIENTO                                          │
│  ├─ Contenedor: in_agendamiento_web                         │
│  ├─ Base de datos: in_agendamiento_db (BD: agendamiento)    │
│  └─ Puerto interno: 8069                                    │
└─────────────────────────────────────────────────────────────┘
```

## Pre-requisitos

- Acceso SSH al servidor
- Docker instalado y funcionando
- Contenedores `nginx-proxy-manager` y `proxy-db` activos
- Tenant ya creado en Odoo con el dominio configurado en el website

## Procedimiento Completo

### Paso 1: Verificar el Tenant en Odoo

Confirmar que el tenant existe y tiene el dominio correcto configurado:

```bash
docker exec in_agendamiento_db psql -U odoo -d agendamiento -c "
SELECT w.id, w.name, w.domain, c.name as company
FROM website w
JOIN res_company c ON w.company_id = c.id
ORDER BY w.id;"
```

Si el dominio está incorrecto, corregirlo:

```bash
docker exec in_agendamiento_db psql -U odoo -d agendamiento -c "
UPDATE website
SET domain = 'https://SUBDOMINIO.innatum.cloud'
WHERE id = ID_DEL_WEBSITE
RETURNING id, name, domain;"
```

### Paso 2: Configurar DNS

En el proveedor de dominio (donde se gestiona `innatum.cloud`), agregar un registro:

```
SUBDOMINIO.innatum.cloud  →  A record  →  [IP del servidor]
```

O usando CNAME:

```
SUBDOMINIO.innatum.cloud  →  CNAME  →  innatum.cloud
```

**Esperar propagación DNS** (puede tomar entre 5 minutos y 24 horas).

### Paso 3: Obtener Token de NPM

```bash
TOKEN=$(curl -s -X POST "http://localhost:81/api/tokens" \
  -H "Content-Type: application/json" \
  -d '{"identity":"admin@admin.com","secret":"##Xtreme12"}' | jq -r '.token')

echo "Token: ${TOKEN:0:20}..."
```

### Paso 4: Crear Proxy Host

```bash
curl -s -X POST "http://localhost:81/api/nginx/proxy-hosts" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "domain_names": ["SUBDOMINIO.innatum.cloud"],
    "forward_scheme": "http",
    "forward_host": "in_agendamiento_web",
    "forward_port": 8069,
    "block_exploits": true,
    "allow_websocket_upgrade": true,
    "http2_support": true,
    "access_list_id": 0,
    "advanced_config": "",
    "meta": {},
    "locations": []
  }'
```

Guardar el `id` del proxy host creado (ej: `"id": 10`).

> ⚠️ **OBLIGATORIO: configuración avanzada de Nginx (websocket / gzip / body size).**
> El proxy host debe llevar una `advanced_config` **idéntica a la del dominio
> principal `innatum.cloud`**. Sin ella, las peticiones `/websocket` de Odoo van
> al puerto HTTP (8069) en lugar del puerto de eventos (8072) y el servidor falla
> con `Couldn't bind the websocket. Is the connection opened on the evented port
> (8072)?`. Consecuencia: el bus del frontend nunca conecta y **NO cargan los
> widgets del sitio web (ej. el botón del chatbot IA no aparece)**.
>
> Esta `advanced_config` se asigna en el Paso 6 (PUT). El bloque exacto:
>
> ```nginx
> client_max_body_size 500m;
>
> gzip on;
> gzip_vary on;
> gzip_proxied any;
> gzip_comp_level 5;
> gzip_min_length 1024;
> gzip_buffers 16 8k;
> gzip_types text/plain text/css text/xml application/json application/javascript application/x-javascript application/xml application/xml+rss image/svg+xml font/woff font/woff2 application/wasm;
>
> location /websocket {
>     proxy_pass http://in_agendamiento_web:8072;
>     proxy_set_header Upgrade $http_upgrade;
>     proxy_set_header Connection "upgrade";
>     proxy_set_header Host $host;
>     proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
>     proxy_set_header X-Forwarded-Proto $scheme;
>     proxy_set_header X-Real-IP $remote_addr;
>     proxy_read_timeout 720s;
>     proxy_send_timeout 720s;
> }
> ```
>
> El script `crear_subdominio.sh` ya incluye este bloque automáticamente.

### Paso 5: Crear Certificado SSL Let's Encrypt

```bash
curl -s -X POST "http://localhost:81/api/nginx/certificates" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "letsencrypt",
    "domain_names": ["SUBDOMINIO.innatum.cloud"],
    "meta": {}
  }' --max-time 120
```

Guardar el `id` del certificado creado (ej: `"id": 16`).

### Paso 6: Asignar Certificado al Proxy Host

Usando el ID del proxy host (paso 4) y el ID del certificado (paso 5):

```bash
curl -s -X PUT "http://localhost:81/api/nginx/proxy-hosts/ID_PROXY_HOST" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "domain_names": ["SUBDOMINIO.innatum.cloud"],
    "forward_scheme": "http",
    "forward_host": "in_agendamiento_web",
    "forward_port": 8069,
    "certificate_id": ID_CERTIFICADO,
    "ssl_forced": true,
    "http2_support": true,
    "block_exploits": true,
    "allow_websocket_upgrade": true,
    "access_list_id": 0,
    "advanced_config": "",
    "caching_enabled": false,
    "meta": {},
    "locations": []
  }'
```

### Paso 7: Verificar Configuración

Verificar en la base de datos de NPM:

```bash
docker exec proxy-db psql -U npm -d npm -c "
SELECT id, domain_names, forward_host, ssl_forced, certificate_id
FROM proxy_host
WHERE domain_names::text LIKE '%SUBDOMINIO%';"
```

Probar acceso HTTPS:

```bash
curl -sI https://SUBDOMINIO.innatum.cloud | head -5
```

Respuesta esperada:

```
HTTP/2 200
server: openresty
...
```

---

## Script Automatizado

Para automatizar todo el proceso, usar este script:

```bash
#!/bin/bash
# Archivo: /home/odoo/clientes/in_agendamiento/scripts/crear_subdominio.sh

SUBDOMINIO=$1

if [ -z "$SUBDOMINIO" ]; then
    echo "Uso: $0 <subdominio>"
    echo "Ejemplo: $0 clinica-dental"
    exit 1
fi

DOMINIO="${SUBDOMINIO}.innatum.cloud"
NPM_USER="admin@admin.com"
NPM_PASS="##Xtreme12"
FORWARD_HOST="in_agendamiento_web"
FORWARD_PORT=8069

echo "=== Configurando $DOMINIO ==="

# Obtener token
echo "[1/4] Obteniendo token de NPM..."
TOKEN=$(curl -s -X POST "http://localhost:81/api/tokens" \
  -H "Content-Type: application/json" \
  -d "{\"identity\":\"$NPM_USER\",\"secret\":\"$NPM_PASS\"}" | jq -r '.token')

if [ "$TOKEN" == "null" ] || [ -z "$TOKEN" ]; then
    echo "ERROR: No se pudo obtener token de NPM"
    exit 1
fi

# Crear proxy host
echo "[2/4] Creando proxy host..."
PROXY_RESULT=$(curl -s -X POST "http://localhost:81/api/nginx/proxy-hosts" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"domain_names\": [\"$DOMINIO\"],
    \"forward_scheme\": \"http\",
    \"forward_host\": \"$FORWARD_HOST\",
    \"forward_port\": $FORWARD_PORT,
    \"block_exploits\": true,
    \"allow_websocket_upgrade\": true,
    \"http2_support\": true,
    \"access_list_id\": 0,
    \"advanced_config\": \"\",
    \"meta\": {},
    \"locations\": []
  }")

PROXY_ID=$(echo $PROXY_RESULT | jq -r '.id')

if [ "$PROXY_ID" == "null" ]; then
    echo "ERROR: No se pudo crear proxy host"
    echo "$PROXY_RESULT"
    exit 1
fi

echo "    Proxy host creado con ID: $PROXY_ID"

# Crear certificado SSL
echo "[3/4] Generando certificado SSL (puede tardar ~30 segundos)..."
CERT_RESULT=$(curl -s -X POST "http://localhost:81/api/nginx/certificates" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"provider\": \"letsencrypt\",
    \"domain_names\": [\"$DOMINIO\"],
    \"meta\": {}
  }" --max-time 120)

CERT_ID=$(echo $CERT_RESULT | jq -r '.id')

if [ "$CERT_ID" == "null" ]; then
    echo "ERROR: No se pudo crear certificado SSL"
    echo "$CERT_RESULT"
    exit 1
fi

echo "    Certificado creado con ID: $CERT_ID"

# Asignar certificado al proxy host
echo "[4/4] Asignando certificado SSL al proxy host..."
UPDATE_RESULT=$(curl -s -X PUT "http://localhost:81/api/nginx/proxy-hosts/$PROXY_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"domain_names\": [\"$DOMINIO\"],
    \"forward_scheme\": \"http\",
    \"forward_host\": \"$FORWARD_HOST\",
    \"forward_port\": $FORWARD_PORT,
    \"certificate_id\": $CERT_ID,
    \"ssl_forced\": true,
    \"http2_support\": true,
    \"block_exploits\": true,
    \"allow_websocket_upgrade\": true,
    \"access_list_id\": 0,
    \"advanced_config\": \"\",
    \"caching_enabled\": false,
    \"meta\": {},
    \"locations\": []
  }")

# Verificar
echo ""
echo "=== Verificando configuración ==="
sleep 2
HTTP_CODE=$(curl -sI "https://$DOMINIO" --max-time 10 2>/dev/null | head -1)

if echo "$HTTP_CODE" | grep -q "200"; then
    echo "✅ $DOMINIO configurado correctamente"
    echo "   URL: https://$DOMINIO"
else
    echo "⚠️  Verificar manualmente: https://$DOMINIO"
    echo "   (El DNS puede tardar en propagarse)"
fi
```

### Uso del Script

```bash
chmod +x /home/odoo/clientes/in_agendamiento/scripts/crear_subdominio.sh
./scripts/crear_subdominio.sh nombre-clinica
```

---

## Comandos de Verificación Útiles

### Ver todos los proxy hosts configurados

```bash
docker exec proxy-db psql -U npm -d npm -c "
SELECT id, domain_names, forward_host, ssl_forced, certificate_id
FROM proxy_host
WHERE is_deleted = 0
ORDER BY id;"
```

### Ver todos los certificados SSL

```bash
docker exec proxy-db psql -U npm -d npm -c "
SELECT id, nice_name, domain_names, expires_on
FROM certificate
ORDER BY id;"
```

### Ver websites en Odoo

```bash
docker exec in_agendamiento_db psql -U odoo -d agendamiento -c "
SELECT w.id, w.name, w.domain, c.name as company
FROM website w
JOIN res_company c ON w.company_id = c.id
ORDER BY w.id;"
```

### Probar conectividad de un subdominio

```bash
curl -sI https://SUBDOMINIO.innatum.cloud | head -10
```

---

## Troubleshooting

### Error: "domain is already in use"

El subdominio ya existe en NPM. Verificar con:

```bash
docker exec proxy-db psql -U npm -d npm -c "
SELECT id, domain_names FROM proxy_host WHERE domain_names::text LIKE '%SUBDOMINIO%';"
```

### Error: DNS no resuelve

Verificar propagación DNS:

```bash
nslookup SUBDOMINIO.innatum.cloud
# o
dig SUBDOMINIO.innatum.cloud
```

### Error: Certificado SSL falla

- Verificar que el DNS esté propagado (Let's Encrypt necesita resolver el dominio)
- Verificar que el puerto 80 esté accesible desde internet
- Revisar logs de NPM: `docker logs nginx-proxy-manager`

### Error: 502 Bad Gateway

El contenedor de Odoo no está accesible:

```bash
# Verificar que el contenedor esté corriendo
docker ps | grep in_agendamiento_web

# Verificar conectividad desde NPM
docker exec nginx-proxy-manager curl -s http://in_agendamiento_web:8069 | head -5
```

---

## Información de Conexión

| Servicio | Host/Contenedor | Puerto | Credenciales |
|----------|-----------------|--------|--------------|
| NPM Panel | localhost | 81 | admin@admin.com / ##Xtreme12 |
| NPM DB | proxy-db | 5432 | npm / #$532jhd%36 |
| Odoo Web | in_agendamiento_web | 8069 | - |
| Odoo DB | in_agendamiento_db | 5432 | odoo / PgWcvHk1ZfIhjttF8UNP |
| Base de datos Odoo | - | - | agendamiento |

---

## Flujo Completo para Nuevo Tenant

```
1. ODOO: Crear tenant via wizard
   └─ Se crea: company + website + usuario admin
   └─ Configurar dominio: https://SUBDOMINIO.innatum.cloud

2. DNS: Agregar registro A/CNAME
   └─ SUBDOMINIO.innatum.cloud → IP del servidor

3. SERVIDOR: Ejecutar script o comandos manuales
   └─ ./scripts/crear_subdominio.sh SUBDOMINIO
   └─ O seguir pasos 3-7 de este documento

4. VERIFICAR: Probar acceso HTTPS
   └─ curl -sI https://SUBDOMINIO.innatum.cloud
```

---

*Documento creado: 2026-06-20*
*Última actualización: 2026-06-20*

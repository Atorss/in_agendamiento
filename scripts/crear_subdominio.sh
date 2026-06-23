#!/bin/bash
# =============================================================================
# Script: crear_subdominio.sh
# Descripcion: Configura un nuevo subdominio en NPM para un tenant de agendamiento
# Uso: ./crear_subdominio.sh <subdominio>
# Ejemplo: ./crear_subdominio.sh clinica-dental
# =============================================================================

SUBDOMINIO=$1

if [ -z "$SUBDOMINIO" ]; then
    echo "Uso: $0 <subdominio>"
    echo "Ejemplo: $0 clinica-dental"
    echo ""
    echo "Esto configurara: https://<subdominio>.innatum.es"
    exit 1
fi

DOMINIO="${SUBDOMINIO}.innatum.es"
NPM_USER="admin@admin.com"
NPM_PASS="##Xtreme12"
FORWARD_HOST="in_agendamiento_web"
FORWARD_PORT=8069

echo "=========================================="
echo " Configurando: $DOMINIO"
echo "=========================================="
echo ""

# Obtener token
echo "[1/4] Obteniendo token de NPM..."
TOKEN=$(curl -s -X POST "http://localhost:81/api/tokens" \
  -H "Content-Type: application/json" \
  -d "{\"identity\":\"$NPM_USER\",\"secret\":\"$NPM_PASS\"}" | jq -r '.token')

if [ "$TOKEN" == "null" ] || [ -z "$TOKEN" ]; then
    echo "ERROR: No se pudo obtener token de NPM"
    echo "Verificar que nginx-proxy-manager este corriendo"
    exit 1
fi
echo "       Token obtenido correctamente"

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
    ERROR_MSG=$(echo $PROXY_RESULT | jq -r '.error.message')
    if echo "$ERROR_MSG" | grep -q "already in use"; then
        echo "       El dominio ya existe en NPM"
        # Obtener el ID existente
        PROXY_ID=$(curl -s "http://localhost:81/api/nginx/proxy-hosts" \
          -H "Authorization: Bearer $TOKEN" | jq -r ".[] | select(.domain_names[0]==\"$DOMINIO\") | .id")
        echo "       Usando proxy host existente ID: $PROXY_ID"
    else
        echo "ERROR: No se pudo crear proxy host"
        echo "$PROXY_RESULT"
        exit 1
    fi
else
    echo "       Proxy host creado con ID: $PROXY_ID"
fi

# Crear certificado SSL
echo "[3/4] Generando certificado SSL Let's Encrypt..."
echo "       (Esto puede tardar 30-60 segundos)"
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
    ERROR_MSG=$(echo $CERT_RESULT | jq -r '.error.message')
    echo "ERROR: No se pudo crear certificado SSL"
    echo "Mensaje: $ERROR_MSG"
    echo ""
    echo "Posibles causas:"
    echo "  - El DNS aun no ha propagado"
    echo "  - El puerto 80 no es accesible desde internet"
    echo ""
    echo "El proxy host fue creado (ID: $PROXY_ID) pero sin SSL."
    echo "Puedes agregar el SSL manualmente desde el panel NPM: http://localhost:81"
    exit 1
fi

CERT_EXPIRES=$(echo $CERT_RESULT | jq -r '.expires_on')
echo "       Certificado creado con ID: $CERT_ID"
echo "       Expira: $CERT_EXPIRES"

# Asignar certificado al proxy host
echo "[4/4] Asignando certificado SSL y habilitando HTTPS..."
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

UPDATE_SSL=$(echo $UPDATE_RESULT | jq -r '.ssl_forced')
if [ "$UPDATE_SSL" == "true" ]; then
    echo "       SSL configurado correctamente"
else
    echo "ADVERTENCIA: Verificar configuracion SSL manualmente"
fi

# Verificar
echo ""
echo "=========================================="
echo " Verificando configuracion"
echo "=========================================="
sleep 3

HTTP_CODE=$(curl -sI "https://$DOMINIO" --max-time 10 2>/dev/null | head -1)

if echo "$HTTP_CODE" | grep -q "200"; then
    echo ""
    echo "  EXITO: $DOMINIO configurado correctamente"
    echo ""
    echo "  URL: https://$DOMINIO"
    echo ""
elif echo "$HTTP_CODE" | grep -q "HTTP"; then
    echo ""
    echo "  PARCIAL: El servidor responde pero con codigo diferente a 200"
    echo "  Respuesta: $HTTP_CODE"
    echo "  URL: https://$DOMINIO"
    echo ""
else
    echo ""
    echo "  PENDIENTE: No se pudo verificar el acceso"
    echo "  El DNS puede tardar en propagarse completamente."
    echo "  URL: https://$DOMINIO"
    echo ""
fi

echo "=========================================="
echo " Resumen"
echo "=========================================="
echo "  Dominio:      $DOMINIO"
echo "  Proxy Host:   ID $PROXY_ID"
echo "  Certificado:  ID $CERT_ID"
echo "  Forward:      $FORWARD_HOST:$FORWARD_PORT"
echo "  SSL Forzado:  Si"
echo "  HTTP/2:       Si"
echo "=========================================="

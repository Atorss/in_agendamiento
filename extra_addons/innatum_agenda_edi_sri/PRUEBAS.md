# Guía de pruebas — `in_edi_sri`

Plan de verificación del módulo de facturación electrónica SRI, de lo más
simple (sin certificado) a lo completo (contra el SRI real). Cada fase es
independiente; valida una antes de pasar a la siguiente.

**Entorno de referencia**
- Contenedor Docker: `odoo18`
- Base de datos: `nutri_juli`
- UI: http://localhost:8018
- Config: `/etc/odoo/odoo.conf`

> Si el servidor está corriendo en el puerto 8069/8018, los comandos de shell
> usan `--http-port 8966` para no chocar con él.

---

## Pre-requisito: instalar / actualizar el módulo

```bash
docker exec -i odoo18 odoo -c /etc/odoo/odoo.conf -d nutri_juli \
  -u in_edi_sri --stop-after-init --http-port 8966
```

Para correr además los tests unitarios:

```bash
docker exec -i odoo18 odoo -c /etc/odoo/odoo.conf -d nutri_juli \
  -u in_edi_sri --test-enable --test-tags /in_edi_sri \
  --stop-after-init --http-port 8966 2>&1 | grep -E "failed|error|tests"
```

✅ Esperado: `0 failed, 0 error(s) of 4 tests`.

---

## Fase A — Humo en la interfaz (sin certificado)

Objetivo: confirmar que el módulo está instalado y es configurable.

1. Entra a http://localhost:8018 (base `nutri_juli`).
2. Activa **modo desarrollador** (Ajustes → al final → Activar modo desarrollador).
3. Verifica los menús:
   - **Contabilidad → Configuración → SRI Certificates** (puede estar vacío).
   - **Contabilidad → Asientos contables → SRI Documents** (vacío).
4. **Contabilidad → Configuración → Ajustes** → bloque **"SRI Electronic
   Invoicing"**: debe mostrar *Environment* (Test/Producción), obligado a
   contabilidad, nombre comercial, dir. matriz, contribuyente especial.
5. Configura la **compañía**: Ajustes → Compañías → tu compañía:
   - **RUC** válido en el campo NIF/VAT (13 dígitos).
   - Dirección (calle).
6. Configura el **diario de ventas**: Contabilidad → Configuración → Diarios →
   "Facturas de cliente" → pestaña **Ajustes avanzados** →
   - Activa **Electronic Invoicing (SRI)**.
   - **estab = 001**, **ptoEmi = 001**.

✅ **Criterio de éxito:** todos los campos existen, se guardan sin error, y la
compañía tiene RUC.

---

## Fase B — Generar e inspeccionar el XML (shell, sin certificado)

Objetivo: probar la **clave de acceso** y el **XML de factura 1.1.0** sin firmar
ni enviar.

1. En la UI crea una **factura de cliente** (cliente con cédula o RUC, una línea
   con producto e IVA 15%) y **Confírmala** (Post).
2. Abre el shell de Odoo:

```bash
docker exec -it odoo18 odoo shell -c /etc/odoo/odoo.conf -d nutri_juli --http-port 8966
```

3. Ejecuta:

```python
from odoo.addons.in_edi_sri.utils import access_key as ak
move = env['account.move'].search(
    [('move_type','=','out_invoice'),('state','=','posted')], limit=1)
doc = env['in_edi.document'].create(
    {'move_id': move.id, 'environment': move.company_id.in_edi_environment})
key, seq = move._in_edi_build_access_key()
doc.write({'access_key': key, 'sequential': seq})
xml = move._in_edi_build_invoice_xml(doc)
print(xml.decode())
print("CLAVE:", key, "VALIDA:", ak.is_valid_access_key(key))
```

4. Sal sin guardar con `Ctrl-D` (no hagas `env.cr.commit()`).

✅ **Criterio de éxito:**
- Se imprime el XML completo (`infoTributaria`, `infoFactura`, `detalles`...).
- `VALIDA: True`.
- `importeTotal` = `totalSinImpuestos` + suma de `valor` de impuestos.

---

## Fase C — Firma con certificado de PRUEBA (sin SRI)

Objetivo: probar la **firma XAdES-BES** de punta a punta dentro de Odoo, usando
un `.p12` autogenerado (el SRI lo rechazará por identidad, pero la firma se
genera igual).

1. Genera un `.p12` de prueba:

```bash
docker exec -i odoo18 python3 - <<'PY'
from datetime import datetime, timedelta, timezone
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,"TEST FIRMA"),
                  x509.NameAttribute(NameOID.ORGANIZATION_NAME,"INNATUM"),
                  x509.NameAttribute(NameOID.COUNTRY_NAME,"EC")])
now = datetime.now(timezone.utc)
cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=365))
        .sign(key, hashes.SHA256()))
data = pkcs12.serialize_key_and_certificates(b"test", key, cert, None,
        serialization.BestAvailableEncryption(b"1234"))
open("/tmp/test.p12","wb").write(data)
print("OK -> /tmp/test.p12  password: 1234")
PY
docker cp odoo18:/tmp/test.p12 /home/saquito/Descargas/test.p12
```

2. En la UI: **Contabilidad → Configuración → SRI Certificates → Nuevo**:
   - Name: "Certificado de prueba".
   - Sube `~/Descargas/test.p12`.
   - Botón **Validate** → contraseña `1234` → extrae titular/emisor/fechas.
   - Botón **Activate**.
3. Abre la factura confirmada → botón **Send to SRI**.
4. Pestaña **SRI** de la factura: revisa el documento creado, descarga el
   **Signed XML** y confirma el bloque `<ds:Signature>` con
   `QualifyingProperties` / `SignedProperties` (XAdES).

✅ **Criterio de éxito:** se genera el XML firmado con estructura XAdES. El
envío al SRI fallará (cert no acreditado) — es lo esperado en esta fase.

---

## Fase D — Prueba real contra el SRI (ambiente de pruebas)

Objetivo: validar el flujo completo Recepción → Autorización contra el SRI.

**Requisitos (los provees tú):**
- Un `.p12` real de una entidad acreditada (Security Data, BCE, Uanataca, etc.)
  o el certificado de pruebas del SRI.
- RUC dado de alta en el **ambiente de pruebas** del SRI (portal SRI →
  Comprobantes electrónicos → solicitar ambiente de pruebas).

**Pasos:**
1. Compañía → **Environment = Test (Pruebas)**.
2. Sube el `.p12` real, **Validate** + **Activate**.
3. Confirma una factura y pulsa **Send to SRI**.
4. Revisa el estado en la pestaña **SRI**:
   - `RECIBIDA` → `AUTORIZADO`: éxito.
   - `DEVUELTA` / `NO AUTORIZADO`: lee los mensajes del SRI (campo *SRI
     Messages*); suelen ser ajustes de canonicalización, formato del issuer o
     catálogos. Anótalos para corregir.
5. Si queda en `sent` (autorización asíncrona pendiente), el cron
   *"SRI: Poll pending authorizations"* la reconsulta cada 30 min; o
   ejecútalo manualmente desde el documento con **Send to SRI** otra vez.

✅ **Criterio de éxito:** una factura llega a estado **Authorized** con número
de autorización y fecha.

---

## Endpoints del SRI usados

| Servicio | Pruebas (celcer) | Producción (cel) |
|----------|------------------|------------------|
| Recepción | `https://celcer.sri.gob.ec/.../RecepcionComprobantesOffline?wsdl` | `https://cel.sri.gob.ec/.../RecepcionComprobantesOffline?wsdl` |
| Autorización | `https://celcer.sri.gob.ec/.../AutorizacionComprobantesOffline?wsdl` | `https://cel.sri.gob.ec/.../AutorizacionComprobantesOffline?wsdl` |

---

## Checklist antes de PRODUCCIÓN

- [ ] Fases A–D superadas en ambiente de pruebas.
- [ ] Configurar el secreto de cifrado en `odoo.conf`:
      `in_edi_master_key = <cadena larga aleatoria>` y reiniciar `odoo18`.
      Sin esto, las contraseñas de los `.p12` se cifran en modo inseguro (lo
      avisa el log con un WARNING).
- [ ] Cambiar la compañía a **Environment = Production**.
- [ ] Cargar el `.p12` de producción (real, acreditado).
- [ ] Verificar la numeración (`secuencial`) del diario antes de emitir.
- [ ] Confirmar que el RUC está autorizado para producción en el SRI.

---

## Alcance actual y pendientes

**Implementado:** factura (codDoc 01), clave de acceso, firma XAdES-BES a nivel
compañía, envío Recepción + Autorización, RIDE PDF, multicompañía.

**Pendiente / fuera de alcance de esta versión:**
- Notas de crédito (04), débito (05), retenciones (07), liquidaciones.
- Distinción IVA 0% vs exento vs no objeto de IVA.
- `formaPago` real (hoy fijo "01" — sin sistema financiero).
- Validación del XML contra el XSD oficial antes de enviar.
- Ajuste fino de la firma según la respuesta real del SRI (issuer name / C14N).

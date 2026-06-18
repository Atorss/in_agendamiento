# Checklist de validación — Fase 1 (aislamiento multi-tenant)

Objetivo: confirmar que dos tenants conviviendo en la misma BD están completamente aislados a nivel datos, controllers públicos y chatbot IA.

> **Cero tolerancia**: si CUALQUIER test falla, NO avanzar a Fase 3. Cada fuga entre tenants es un blocker.

---

## Setup inicial

### 0.1 BD limpia
- [ ] Crear BD `agendamiento` limpia (sin demo data) ✅ ya hecho
- [ ] Confirmar que `odoo.conf` tiene en `addons_path` la ruta `/mnt/extra-addons/in_agendamiento` (dentro del contenedor) — equivalente a `/home/saquito/proyecto/odoo-docker-build-18/odoo/18/extra-addons/in_agendamiento` en el host

### 0.2 Instalar módulos (en orden)
- [ ] `innatum_agenda_core` (18.0.3.0.0)
- [ ] `innatum_agenda_web` (18.0.1.1.0)
- [ ] `innatum_ai` (18.0.1.4.0)
- [ ] `innatum_ai_web` (18.0.1.1.0)
- [ ] Verificar en log: `Module innatum_agenda_core: loaded` sin errores

### 0.3 Crear 2 tenants

**Tenant A — "Peluquería Estilo"**
- [ ] Settings → Companies → Crear: name=`Peluquería Estilo`, currency=USD, timezone=`America/Lima`
- [ ] Website → Configuration → Websites → Crear: name=`Peluquería Estilo`, domain=`http://estilo.localhost:8069`, company=Peluquería Estilo
- [ ] User: `admin_estilo@test.com`, **Allowed Companies = SOLO Peluquería**, Default = Peluquería, grupo `Innatum Agenda → Administrador`

**Tenant B — "Veterinaria PetCare"**
- [ ] Crear company `Veterinaria PetCare`, timezone=`America/Guayaquil`
- [ ] Website `PetCare`, domain=`http://petcare.localhost:8069`, company=Veterinaria
- [ ] User `admin_petcare@test.com`, **Allowed Companies = SOLO Veterinaria**, grupo administrador agenda

### 0.4 Mapear localhost a subdominios (para testing local)
- [ ] Editar `/etc/hosts`:
  ```
  127.0.0.1   estilo.localhost
  127.0.0.1   petcare.localhost
  ```

### 0.5 Datos iniciales en cada tenant
Loguearse como `admin_estilo` y crear:
- [ ] Servicio: `Corte de pelo` (code=`CORTE`)
- [ ] Empleado profesional: `María Estilista` (vinculada a user con grupo Usuario de Agenda)
- [ ] Planificación: María, hoy a 7 días, L-V 9-17h, duración 30min → **Aprobar**
- [ ] Verificar que se generaron turnos en `Agenda → Turnos`

Loguearse como `admin_petcare` y crear:
- [ ] Servicio: `Consulta veterinaria` (code=`CONSV`)
- [ ] Empleado: `Dr. Juan Vet`
- [ ] Planificación: Juan, L-V 8-16h → Aprobar

---

## Tests de aislamiento — sitio público

### 1.1 Homepage por subdominio
- [ ] Abrir `http://estilo.localhost:8069/` en navegador **anónimo**
- [ ] ✅ Debe listar SOLO a María Estilista y SOLO el servicio "Corte de pelo"
- [ ] ❌ NO debe aparecer Dr. Juan Vet ni "Consulta veterinaria"
- [ ] Abrir `http://petcare.localhost:8069/` en otra ventana anónima
- [ ] ✅ Debe listar SOLO a Dr. Juan Vet y "Consulta veterinaria"

### 1.2 Endpoint `/citas/get_professionals`
- [ ] En `estilo.localhost:8069/citas`, abrir DevTools → Network
- [ ] Seleccionar servicio "Corte de pelo" en el form
- [ ] ✅ Request `/citas/get_professionals` devuelve solo `María Estilista`
- [ ] Repetir en `petcare.localhost:8069/citas` con "Consulta veterinaria"
- [ ] ✅ Solo devuelve `Dr. Juan Vet`

### 1.3 Endpoint `/citas/get_available_slots` respeta TZ del tenant
- [ ] En Peluquería (TZ Lima, UTC-5), seleccionar fecha
- [ ] ✅ Slots empiezan a las **09:00 hora Lima** (verificar formato hora)
- [ ] En Veterinaria (TZ Guayaquil, UTC-5), también UTC-5 pero distinta company
- [ ] ✅ Slots empiezan a las **08:00** según planificación de Juan

### 1.4 Cross-tenant booking attack — el test crítico
- [ ] En `estilo.localhost`, abrir DevTools → Network
- [ ] Completar form de reserva en Peluquería, hacer submit, capturar el `turno_id` del POST
- [ ] Anotar un `turno_id` del tenant B (Veterinaria) buscando en backend
- [ ] Usando curl o el DevTools, hacer POST a `http://estilo.localhost:8069/citas/submit` con:
  - `turno_id` = el ID del turno de Veterinaria
  - Resto de campos válidos
- [ ] ✅ **Debe responder con error**: "El horario seleccionado ya no está disponible"
- [ ] ✅ El turno de Veterinaria sigue en estado `available` (no se reservó)

---

## Tests de partner multi-tenant

### 2.1 Mismo VAT en 2 tenants
- [ ] En `estilo.localhost/citas`, reservar como `Carlos Pérez`, VAT=`1234567890`, email=`carlos@trabajo.com`
- [ ] ✅ Reserva exitosa, partner creado en company Peluquería
- [ ] En `petcare.localhost/citas`, reservar como `Carlos Pérez`, VAT=`1234567890`, email=`carlos@personal.com`
- [ ] ✅ Reserva exitosa, NUEVO partner creado en company Veterinaria (no falla por unicidad VAT)
- [ ] Backend: en cada tenant verificar `Contacts` → existe 1 Carlos Pérez con su email correspondiente

### 2.2 Aislamiento de partners
- [ ] Como `admin_estilo`, abrir Contacts → buscar VAT `1234567890`
- [ ] ✅ Solo aparece el Carlos de Peluquería (email `carlos@trabajo.com`)
- [ ] ❌ NO aparece el Carlos de Veterinaria
- [ ] Repetir como `admin_petcare`
- [ ] ✅ Solo aparece el Carlos de Veterinaria

### 2.3 M2M `servicios_consumidos_ids`
- [ ] Como `admin_estilo`, abrir Carlos Pérez (de Peluquería)
- [ ] ✅ `servicios_consumidos_ids` contiene solo `Corte de pelo`
- [ ] Como `admin_petcare`, abrir Carlos Pérez (de Veterinaria)
- [ ] ✅ `servicios_consumidos_ids` contiene solo `Consulta veterinaria`
- [ ] Reservar OTRO turno de "Corte de pelo" con el mismo Carlos en Peluquería
- [ ] ✅ El M2M sigue teniendo 1 solo servicio (no se duplica, es idempotente)

---

## Tests de record rules — backend

### 3.1 Operator del tenant A no ve datos del tenant B
- [ ] Loguearse como `admin_estilo`
- [ ] Ir a `Agenda → Turnos`
- [ ] ✅ Solo ve turnos de María Estilista (Peluquería)
- [ ] ❌ NO ve turnos de Dr. Juan Vet (Veterinaria)
- [ ] Ir a `Agenda → Servicios`
- [ ] ✅ Solo ve "Corte de pelo"
- [ ] ❌ NO ve "Consulta veterinaria"

### 3.2 Switch de company en multi-company allowed
- [ ] Crear un user `super_admin@test.com` con `Allowed Companies = [Peluquería, Veterinaria]`
- [ ] Loguearse como super_admin
- [ ] Switch a Peluquería en company selector
- [ ] ✅ En Turnos ve solo Peluquería
- [ ] Switch a Veterinaria
- [ ] ✅ En Turnos ve solo Veterinaria

### 3.3 Global rules aplican con `sudo()`
Este test requiere shell. Como Innatum admin:
```bash
docker exec -it odoo-app /odoo/odoo-bin shell -d agendamiento --no-http
```
```python
>>> peluqueria = env['res.company'].search([('name', '=', 'Peluquería Estilo')])
>>> # Forzar contexto company de Peluquería
>>> turnos = env['innatum.agenda.turno'].with_company(peluqueria).sudo().search([])
>>> set(turnos.mapped('company_id.name'))
{'Peluquería Estilo'}  # ✅ solo Peluquería, aunque usamos sudo()
```
- [ ] ✅ Confirma que la global rule no se bypassa con sudo

---

## Tests del chatbot IA (si tenés provider configurado)

### 4.1 Aislamiento de servicios listados
- [ ] En `estilo.localhost`, abrir chatbot, identificarse con VAT `1234567890`
- [ ] Pedirle "muéstrame los servicios disponibles"
- [ ] ✅ Solo lista "Corte de pelo"
- [ ] ❌ NO lista "Consulta veterinaria"
- [ ] Repetir en `petcare.localhost` con otro VAT
- [ ] ✅ Solo lista "Consulta veterinaria"

### 4.2 Sesión cross-tenant attack
- [ ] Iniciar sesión chatbot en `estilo.localhost`, capturar `token` del response `/chatbot/start`
- [ ] Hacer POST a `petcare.localhost:8069/chatbot/send` con ese `token`
- [ ] ✅ Debe responder `session_expired` (no encuentra sesión bajo el company de Veterinaria)

### 4.3 Reserva por chatbot solo crea turnos del tenant
- [ ] Completar flujo de reserva por chatbot en Peluquería
- [ ] ✅ Verificar que `turno.company_id` = Peluquería
- [ ] ✅ Verificar que `partner.company_id` = Peluquería

---

## Checklist final — antes de avanzar a Fase 3

- [ ] Todos los tests 1.x pasaron (aislamiento sitio público)
- [ ] Todos los tests 2.x pasaron (partners multi-tenant)
- [ ] Todos los tests 3.x pasaron (record rules backend)
- [ ] Todos los tests 4.x pasaron (chatbot IA) — si aplica
- [ ] No hay errores en log de Odoo durante los tests
- [ ] Capturas de pantalla de los 2 sitios públicos lado a lado mostrando data distinta (evidencia para mostrar)

## Si algún test falla

1. Anotar el test que falló y el comportamiento observado
2. Inspeccionar `request.website.id` y `request.website.company_id` con `?debug=1`
3. Pegarme el síntoma y el log relevante para que arregle antes de Fase 3

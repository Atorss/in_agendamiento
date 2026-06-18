# -*- coding: utf-8 -*-
"""Primitives de agendamiento — capa stateless reusable.

Son los bloques mínimos que orquestan los flujos de citas: listar servicios,
listar profesionales, buscar disponibilidad y reservar un turno existente.

Reglas:
- NO conocen el concepto de "sesión" (web o WhatsApp). Reciben todo por parámetro.
- NO deciden qué mensaje devolverle al cliente. El llamador (chatbot web /
  agente WhatsApp) compone el texto a partir del dict que estas primitives
  devuelven.
- Respetan multi-tenant: si se les pasa `company`, filtran y ejecutan con
  `with_company(company)`. Si no, usan `self.env.company`.
- Trabajan con `servicio.code` (string semántico) como discriminador del LLM,
  no IDs internos.

Las consumen:
- `innatum.ai.chatbot` (chatbot web)  → mismas reglas que ya tenía
- `flow.scheduling.tools` (agente WhatsApp)
"""
import logging
import unicodedata
from datetime import datetime, timedelta

import pytz

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

TZ = pytz.timezone('America/Guayaquil')

_DIAS = {
    'Monday': 'Lunes', 'Tuesday': 'Martes', 'Wednesday': 'Miércoles',
    'Thursday': 'Jueves', 'Friday': 'Viernes', 'Saturday': 'Sábado',
    'Sunday': 'Domingo',
}


def _fecha_es(dt):
    """Formatea datetime a 'Lunes 24/03/2026' en español."""
    dia_en = dt.strftime('%A')
    dia_es = _DIAS.get(dia_en, dia_en)
    return f"{dia_es} {dt.strftime('%d/%m/%Y')}"


def _normalize(s):
    """Lowercase, sin acentos, sin _ ni - extra, espacios colapsados.

    Permite matchear 'odontologia_general' contra 'Odontología General'.
    Usado para fuzzy match cuando el LLM manda un slug en vez del code real.
    """
    if not s:
        return ''
    s = unicodedata.normalize('NFKD', s).encode('ASCII', 'ignore').decode('ASCII')
    s = s.lower().replace('_', ' ').replace('-', ' ')
    return ' '.join(s.split())


def _resolve_servicio(env_servicio, raw_input, company):
    """Resuelve un Servicio a partir de un string libre.

    Estrategia (en orden):
      1. Match exacto por code (case insensitive)
      2. Match exacto por name (case insensitive)
      3. Match normalizado (sin acentos, sin _ , etc.) contra code o name de
         cualquier servicio habilitado para la company

    Devuelve recordset (puede estar vacío).
    """
    raw = (raw_input or '').strip()
    if not raw:
        return env_servicio.browse()

    # 1) Match por code exacto
    s = env_servicio.search([
        ('code', '=ilike', raw),
        ('company_ids', 'in', company.id),
    ], limit=1)
    if s:
        return s

    # 2) Match por name exacto
    s = env_servicio.search([
        ('name', '=ilike', raw),
        ('company_ids', 'in', company.id),
    ], limit=1)
    if s:
        return s

    # 3) Fuzzy match normalizado: comparar contra TODOS los servicios del tenant
    target = _normalize(raw)
    if not target:
        return env_servicio.browse()
    candidates = env_servicio.search([
        ('company_ids', 'in', company.id),
    ])
    for c in candidates:
        if _normalize(c.code) == target or _normalize(c.name) == target:
            return c
    return env_servicio.browse()


class SchedulingPrimitives(models.AbstractModel):
    _name = 'innatum.agenda.scheduling.primitives'
    _description = 'Primitives stateless de agendamiento (reusables)'

    # ------------------------------------------------------------------
    # Helpers de contexto
    # ------------------------------------------------------------------

    def _resolve_company(self, company):
        if company:
            return company
        return self.env.company

    def _with_co(self, company):
        return self.with_company(self._resolve_company(company))

    def _format_price(self, amount, company):
        """Formatea un precio con la moneda de la company. Ej: '$25.00'.

        Respeta la posición del símbolo (antes/después) de la moneda.
        """
        currency = company.currency_id
        amount_str = '%.2f' % amount
        if currency and currency.symbol:
            if currency.position == 'after':
                return '%s %s' % (amount_str, currency.symbol)
            return '%s%s' % (currency.symbol, amount_str)
        return amount_str

    # ------------------------------------------------------------------
    # Primitive 1: list_services
    # ------------------------------------------------------------------

    @api.model
    def list_services(self, company=None):
        """Devuelve servicios habilitados para el tenant con flag de disponibilidad.

        Shape del response (idéntico al que consume el chatbot web):
            {'total': int, 'especialidades': [{'name': str, 'code': str}]}
        Si no hay servicios disponibles:
            {'message': str, 'servicios': []}
        """
        company = self._resolve_company(company)
        Servicio = self._with_co(company).env['innatum.agenda.servicio'].sudo()
        Turno = self._with_co(company).env['innatum.agenda.turno'].sudo()
        servicios = Servicio.search([('company_ids', 'in', company.id)])

        # El campo `precio` lo aporta el módulo innatum_agenda_facturacion. Si
        # no está instalado, simplemente no se reporta precio (no se inventa).
        has_precio = 'precio' in Servicio._fields

        disponibles = []
        for s in servicios:
            tiene = Turno.search([
                ('servicio_ids', 'in', s.id),
                ('state', '=', 'available'),
                ('publicar', '=', True),
                ('date_start', '>=', fields.Datetime.now()),
                ('company_id', '=', company.id),
            ], limit=1)
            if tiene:
                item = {'name': s.name, 'code': s.code}
                # Solo reportamos precio si está configurado (> 0). Un 0.0
                # suele significar "sin precio cargado", no "gratis".
                precio = s.precio if has_precio else 0.0
                if precio and precio > 0:
                    item['precio'] = precio
                    item['precio_label'] = self._format_price(precio, company)
                disponibles.append(item)

        if not disponibles:
            return {
                'message': 'No hay servicios con disponibilidad actualmente.',
                'servicios': [],
            }

        return {
            'total': len(disponibles),
            'especialidades': disponibles,
        }

    # ------------------------------------------------------------------
    # Primitive 2: list_professionals
    # ------------------------------------------------------------------

    @api.model
    def list_professionals(self, servicio_code=None, company=None):
        """Lista profesionales con turnos disponibles, opcionalmente por servicio.

        Shape:
            {'total_professionals': int,
             'professionals': [{'nombre': str, 'turnos_disponibles': int}],
             'nota'?: str}
        Si no hay:
            {'message': str, 'professionals': []}
        """
        company = self._resolve_company(company)
        Turno = self._with_co(company).env['innatum.agenda.turno'].sudo()
        Servicio = self._with_co(company).env['innatum.agenda.servicio'].sudo()

        domain = [
            ('state', '=', 'available'),
            ('publicar', '=', True),
            ('date_start', '>=', fields.Datetime.now()),
            ('company_id', '=', company.id),
        ]

        servicio = _resolve_servicio(Servicio, servicio_code, company)
        if servicio:
            domain.append(('servicio_ids', 'in', servicio.id))

        turnos = Turno.search(domain)
        profesionales = {}
        for t in turnos:
            prof = t.professional_id
            if prof.id not in profesionales:
                profesionales[prof.id] = {
                    'nombre': prof.name,
                    'turnos_disponibles': 0,
                }
            profesionales[prof.id]['turnos_disponibles'] += 1

        if not profesionales:
            return {
                'message': 'No hay profesionales con disponibilidad actualmente.',
                'professionals': [],
            }

        result = {
            'total_professionals': len(profesionales),
            'professionals': list(profesionales.values()),
        }

        if len(profesionales) == 1:
            prof_info = list(profesionales.values())[0]
            result['nota'] = (
                f"Solo hay un profesional disponible: {prof_info['nombre']}. "
                f"Busca disponibilidad INMEDIATAMENTE sin preguntar al cliente."
            )

        return result

    # ------------------------------------------------------------------
    # Primitive 3: summarize_schedule
    # ------------------------------------------------------------------

    @api.model
    def summarize_schedule(self, servicio_code, company=None):
        """Resume el régimen de atención de un servicio.

        Útil para que el agente diga "Atendemos Lun-Vie 9-17, ¿qué día prefieres?"
        en vez de listar 30 turnos sueltos. Lee innatum.agenda.config aprobadas
        y agrupa días+horarios. También sugiere las próximas fechas con cupo.

        Shape:
          {
            'servicio': str, 'code': str,
            'bloques': [
              {'professional': str, 'dias': [str],
               'horario_text': '08:00 - 17:00',
               'duracion_turno_min': int}
            ],
            'proximas_fechas_con_cupo': [
              {'fecha_iso': 'YYYY-MM-DD',
               'fecha_label': 'Lunes 27/05/2026',
               'cupos': int}
            ]
          }
        Error:
          {'error': str}
        """
        company = self._resolve_company(company)
        Servicio = self._with_co(company).env['innatum.agenda.servicio'].sudo()
        Config = self._with_co(company).env['innatum.agenda.config'].sudo()
        Turno = self._with_co(company).env['innatum.agenda.turno'].sudo()

        servicio = _resolve_servicio(Servicio, servicio_code, company)
        if not servicio:
            return {
                'error': f'Servicio no encontrado: "{servicio_code}". '
                         'Usa el campo `code` EXACTO devuelto por consultar_servicios.',
            }

        # Bloques: días + horario únicos del régimen
        configs = Config.search([
            ('servicio_ids', 'in', servicio.id),
            ('state', '=', 'approved'),
        ])

        dias_fields = [
            ('lunes', 'Lunes'), ('martes', 'Martes'),
            ('miercoles', 'Miércoles'), ('jueves', 'Jueves'),
            ('viernes', 'Viernes'), ('sabado', 'Sábado'),
            ('domingo', 'Domingo'),
        ]

        def _hora_to_str(f):
            if not f:
                return '00:00'
            h = int(f)
            m = int(round((f - h) * 60))
            return f'{h:02d}:{m:02d}'

        bloques = []
        seen_blk = set()
        for cfg in configs:
            for line in cfg.line_ids:
                dias = [
                    label for fname, label in dias_fields
                    if getattr(line, fname, False)
                ]
                if not dias:
                    continue
                horario = (f'{_hora_to_str(line.hora_inicio)} - '
                           f'{_hora_to_str(line.hora_fin)}')
                key = (cfg.professional_id.id, tuple(dias), horario)
                if key in seen_blk:
                    continue
                seen_blk.add(key)
                bloques.append({
                    'professional': cfg.professional_id.name,
                    'dias': dias,
                    'horario_text': horario,
                    'duracion_turno_min': (
                        int(cfg.duracion_turno) if cfg.duracion_turno else 30
                    ),
                })

        # Próximas fechas con cupo (max 5)
        turnos = Turno.search([
            ('servicio_ids', 'in', servicio.id),
            ('state', '=', 'available'),
            ('publicar', '=', True),
            ('date_start', '>=', fields.Datetime.now()),
            ('company_id', '=', company.id),
        ], order='date_start asc')

        fechas_cupo = {}
        for t in turnos:
            dt_local = pytz.UTC.localize(t.date_start).astimezone(TZ)
            fecha_iso = dt_local.strftime('%Y-%m-%d')
            if fecha_iso not in fechas_cupo:
                fechas_cupo[fecha_iso] = {
                    'fecha_iso': fecha_iso,
                    'fecha_label': _fecha_es(dt_local),
                    'cupos': 0,
                }
            fechas_cupo[fecha_iso]['cupos'] += 1

        proximas = sorted(
            fechas_cupo.values(), key=lambda x: x['fecha_iso']
        )[:5]

        return {
            'servicio': servicio.name,
            'code': servicio.code,
            'bloques': bloques,
            'proximas_fechas_con_cupo': proximas,
        }

    # ------------------------------------------------------------------
    # Primitive 4: find_availability
    # ------------------------------------------------------------------

    @api.model
    def find_availability(self, servicio_code, profesional_nombre=None,
                          fecha=None, periodo=None, company=None):
        """Busca turnos disponibles para un servicio.

        Args:
          servicio_code: código del servicio (obligatorio).
          profesional_nombre: filtro opcional por nombre parcial.
          fecha: 'YYYY-MM-DD' opcional. Si None, busca próximos 14 días.
          periodo: 'AM' / 'PM' opcional. Si se pasa, filtra a slots de
                   ese período (AM=hora<12, PM=hora>=12). Útil para hacer
                   el "embudo" cuando hay muchos slots en un día.
          company: tenant. Si None usa self.env.company.

        Shape:
            {'especialidad': str, 'especialidad_codigo': str,
             'total_disponibles': int, 'periodo': str?,
             'slots': [{'turno_id', 'professional', 'fecha', 'hora',
                        'duracion_min', 'servicio_codigo'}]}
        Errores:
            {'error': str}
        Sin resultados:
            {'message': str, 'slots': []}
        """
        company = self._resolve_company(company)
        Turno = self._with_co(company).env['innatum.agenda.turno'].sudo()
        Servicio = self._with_co(company).env['innatum.agenda.servicio'].sudo()

        codigo = (servicio_code or '').strip()
        if not codigo:
            return {'error': 'servicio_code es obligatorio'}

        servicio = _resolve_servicio(Servicio, codigo, company)
        if not servicio:
            return {
                'error': f'Servicio no encontrado: "{codigo}". '
                         'Usa el campo `code` EXACTO devuelto por '
                         'consultar_servicios (ej. "1233"), no el nombre.',
            }

        now = datetime.now(TZ)
        if fecha:
            try:
                fecha_local = TZ.localize(
                    datetime.strptime(fecha, '%Y-%m-%d').replace(hour=0, minute=0))
                fecha_fin = fecha_local + timedelta(days=1)
            except ValueError:
                return {'error': f'Formato de fecha inválido: {fecha}. Usa YYYY-MM-DD.'}
        else:
            fecha_local = now
            fecha_fin = now + timedelta(days=14)

        fecha_utc_start = fecha_local.astimezone(pytz.UTC).replace(tzinfo=None)
        fecha_utc_end = fecha_fin.astimezone(pytz.UTC).replace(tzinfo=None)

        domain = [
            ('servicio_ids', 'in', servicio.id),
            ('state', '=', 'available'),
            ('publicar', '=', True),
            ('date_start', '>=', max(fecha_utc_start, fields.Datetime.now())),
            ('date_start', '<', fecha_utc_end),
            ('company_id', '=', company.id),
        ]

        profesional_nombre = (profesional_nombre or '').strip()
        if profesional_nombre:
            domain.append(('professional_id.name', 'ilike', profesional_nombre))

        turnos = Turno.search(domain, order='date_start asc', limit=30)

        if not turnos:
            msg = f'No hay turnos disponibles para {servicio.name}'
            if fecha:
                msg += f' el {fecha}'
            msg += '. Intenta con otra fecha o servicio.'
            return {'message': msg, 'slots': []}

        def _periodo_de_hora(h):
            """Devuelve AM (<12), PM (12-17), NIGHT (>=18)."""
            if h < 12:
                return 'AM'
            if h < 18:
                return 'PM'
            return 'NIGHT'

        slots = []
        for turno in turnos:
            dt_local = pytz.UTC.localize(turno.date_start).astimezone(TZ)
            slots.append({
                'turno_id': turno.id,
                'professional': turno.professional_id.name,
                'fecha': _fecha_es(dt_local),
                'fecha_iso': dt_local.strftime('%Y-%m-%d'),
                'hora': dt_local.strftime('%H:%M'),
                'periodo': _periodo_de_hora(dt_local.hour),
                'duracion_min': int(turno.duration) if turno.duration else 30,
                'servicio_codigo': servicio.code,
            })

        # Filtrar por período si vino el param (embudo AM/PM/NIGHT)
        periodo_norm = (periodo or '').strip().upper() if periodo else None
        if periodo_norm in ('AM', 'PM', 'NIGHT'):
            slots = [s for s in slots if s['periodo'] == periodo_norm]

        result = {
            'especialidad': servicio.name,
            'especialidad_codigo': servicio.code,
            'total_disponibles': len(slots),
            'slots': slots,
        }
        if periodo_norm:
            result['periodo'] = periodo_norm

        if fecha:
            am = [s for s in slots if s['periodo'] == 'AM']
            pm = [s for s in slots if s['periodo'] == 'PM']
            night = [s for s in slots if s['periodo'] == 'NIGHT']
            result['agrupado_por_periodo'] = {
                'AM': am, 'PM': pm, 'NIGHT': night,
            }
            result['total_am'] = len(am)
            result['total_pm'] = len(pm)
            result['total_night'] = len(night)
            if not periodo_norm and len(slots) > 10:
                periodos_con_cupo = [
                    p for p, n in (('mañana', len(am)),
                                   ('tarde', len(pm)),
                                   ('noche', len(night))) if n
                ]
                result['hint_periodo'] = (
                    f'Hay {len(slots)} turnos ese día. Preguntale al cliente '
                    f'en qué período prefiere: {", ".join(periodos_con_cupo)}. '
                    f'El sistema mostrará botones automáticamente.'
                )
        else:
            result['hint'] = (
                'Resultado SIN fecha específica. Considera llamar antes a '
                '`consultar_regimen_servicio` y pedirle al cliente un día. '
                'Después llamá find_availability con fecha=YYYY-MM-DD.'
            )

        return result

    # ------------------------------------------------------------------
    # Primitive 4: reserve_existing
    # ------------------------------------------------------------------

    @api.model
    def reserve_existing(self, turno_id, partner_id, servicio_code=None,
                         motivo=None, company=None):
        """Reserva un turno EXISTENTE (pre-generado por innatum.agenda.config).

        El llamador es responsable de tener identificado al cliente
        (`partner_id` obligatorio).

        Args:
          turno_id: ID del turno a reservar (de find_availability).
          partner_id: ID del cliente ya identificado.
          servicio_code: opcional, requerido solo si el turno ofrece varios.
          motivo: opcional, nota interna.
          company: tenant.

        Shape éxito:
            {'exito': True, 'turno_id': int, 'referencia': str,
             'especialidad': str, 'professional': str,
             'fecha': str, 'hora': str, 'paciente': str,
             'estado': str, 'mensaje': str}
        Errores:
            {'error': str}
        """
        company = self._resolve_company(company)
        Turno = self._with_co(company).env['innatum.agenda.turno'].sudo()
        Partner = self._with_co(company).env['res.partner'].sudo()

        if not turno_id:
            return {'error': 'Se requiere turno_id.'}
        if not partner_id:
            return {'error': 'Se requiere partner_id (cliente identificado).'}

        turno = Turno.browse(int(turno_id))
        if not turno.exists():
            return {'error': 'El turno no existe.'}
        if turno.company_id and turno.company_id.id != company.id:
            return {'error': 'El turno no pertenece a este tenant.'}
        if turno.state != 'available':
            return {'error': 'Este turno ya no está disponible. '
                             'Por favor elige otro horario.'}

        partner = Partner.browse(int(partner_id))
        if not partner.exists():
            return {'error': 'El cliente no existe.'}

        # Determinar servicio elegido. Prioridad:
        # 1. servicio_code explícito (debe estar en servicio_ids del turno)
        # 2. turno.servicio_id ya seteado
        # 3. turno.servicio_ids con un solo elemento
        # 4. error: pedir al cliente que elija
        servicio_elegido = False
        codigo_param = (servicio_code or '').strip().upper()
        if codigo_param:
            match = turno.servicio_ids.filtered(
                lambda s: (s.code or '').upper() == codigo_param
            )
            if match:
                servicio_elegido = match[0]
        if not servicio_elegido:
            if turno.servicio_id:
                servicio_elegido = turno.servicio_id
            elif len(turno.servicio_ids) == 1:
                servicio_elegido = turno.servicio_ids
            else:
                opciones = ', '.join(
                    f'{s.name} (código {s.code})' for s in turno.servicio_ids
                )
                return {
                    'error': (
                        'Este horario ofrece varios servicios. '
                        f'Indica cuál quieres reservar: {opciones}.'
                    ),
                }

        motivo = (motivo or '').strip()

        turno.write({
            'partner_id': partner.id,
            'servicio_id': servicio_elegido.id,
            'notes': motivo or False,
        })
        turno.action_reserve()

        dt_local = pytz.UTC.localize(turno.date_start).astimezone(TZ)

        return {
            'exito': True,
            'turno_id': turno.id,
            'referencia': turno.name,
            'especialidad': turno.servicio_id.name if turno.servicio_id else '',
            'professional': turno.professional_id.name,
            'fecha': _fecha_es(dt_local),
            'hora': dt_local.strftime('%H:%M'),
            'paciente': partner.name,
            'estado': 'Reservado - Pendiente de confirmación',
            'mensaje': '¡Cita reservada exitosamente!',
        }

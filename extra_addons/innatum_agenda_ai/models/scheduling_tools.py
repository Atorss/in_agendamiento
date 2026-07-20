# -*- coding: utf-8 -*-
"""Métodos Python que ejecutan las tools de agendamiento del agente WhatsApp.

Cada método aquí matchea con una fila de `innatum.ai.tool` (tool_type='wa_agent')
cuyo `python_method_path` apunta acá. Firma uniforme:

    def metodo(self, params: dict, session=None) -> dict

`session` es el record `innatum.ai.session` o None (defensivo).
El resultado es un dict serializable que se inyecta como tool_result al LLM.

Las primitives de scheduling (listar, buscar, reservar) están en
`innatum.agenda.scheduling.primitives` y son compartidas con el chatbot web.
Estas tools son wrappers delgados que:
  - Resuelven el tenant (company) desde la sesión
  - Adaptan params del LLM al contrato de las primitives
  - Cumplen los pasos específicos de WhatsApp (identificar cliente, handoff)
"""
import logging

from odoo import api, fields, models
# Fecha en español (Lunes 24/03/2026): `%A` crudo da 'Monday'.
from odoo.addons.innatum_agenda_core.models.scheduling_primitives import (
    _fecha_es,
)

_logger = logging.getLogger(__name__)


class SchedulingTools(models.AbstractModel):
    _name = 'flow.scheduling.tools'
    _description = 'Scheduling tools (Familia A) — agente WhatsApp'

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _company(self, session):
        if session and session.company_id:
            return session.company_id
        return self.env.company

    # -------------------------------------------------------------------------
    # Tool 1: consultar_servicios → primitives.list_services
    # -------------------------------------------------------------------------

    @api.model
    def consultar_servicios(self, params, session=None):
        Primitives = self.env['innatum.agenda.scheduling.primitives']
        return Primitives.list_services(company=self._company(session))

    # -------------------------------------------------------------------------
    # Tool 2: consultar_profesionales → primitives.list_professionals
    # -------------------------------------------------------------------------

    @api.model
    def consultar_profesionales(self, params, session=None):
        params = params or {}
        Primitives = self.env['innatum.agenda.scheduling.primitives']
        return Primitives.list_professionals(
            servicio_code=params.get('servicio_code'),
            company=self._company(session),
        )

    # -------------------------------------------------------------------------
    # Tool 3: buscar_horarios_disponibles → primitives.find_availability
    # -------------------------------------------------------------------------

    @api.model
    def buscar_horarios_disponibles(self, params, session=None):
        params = params or {}
        Primitives = self.env['innatum.agenda.scheduling.primitives']
        return Primitives.find_availability(
            servicio_code=params.get('servicio_code'),
            profesional_nombre=params.get('profesional_nombre'),
            fecha=params.get('fecha'),
            periodo=params.get('periodo'),
            company=self._company(session),
        )

    # -------------------------------------------------------------------------
    # Tool 3.5: consultar_regimen_servicio → primitives.summarize_schedule
    # -------------------------------------------------------------------------

    @api.model
    def consultar_regimen_servicio(self, params, session=None):
        """Resume el régimen de atención de un servicio.

        Devuelve: días/horarios de atención + próximas fechas con cupo.
        El agente lo usa para preguntarle al cliente UN día (en vez de listar
        todos los turnos sueltos).
        """
        params = params or {}
        Primitives = self.env['innatum.agenda.scheduling.primitives']
        return Primitives.summarize_schedule(
            servicio_code=params.get('servicio_code'),
            company=self._company(session),
        )

    # -------------------------------------------------------------------------
    # Tool 4: identificar_cliente — específico de WhatsApp
    # -------------------------------------------------------------------------

    @api.model
    def identificar_cliente(self, params, session=None):
        """Busca/crea el partner del cliente y lo vincula a la sesión.

        Reglas críticas (lecciones aprendidas):
        - NO usar `session.wa_from` como default de phone para buscar. Si lo
          hacés, traés partners viejos creados por OTRO cliente que usó el
          mismo número WhatsApp en sesiones anteriores (ej. miembros de la
          misma familia que reservan desde el mismo celular).
        - SIEMPRE actualizar session.partner_id al partner del resultado.
          Si solo se setea cuando está vacío, una sesión persistente puede
          quedar pegada a un partner viejo.
        - Solo buscar por phone si el LLM lo pasa EXPLÍCITO. Si no, asumimos
          cliente nuevo y creamos.
        """
        params = params or {}
        company = self._company(session)
        vat = (params.get('vat') or '').strip()
        email = (params.get('email') or '').strip().lower()
        phone = (params.get('phone') or '').strip()  # SIN default a wa_from
        name = (params.get('name') or '').strip()

        Partner = self.env['res.partner'].sudo()

        partner = None
        # 1) Match por VAT (más confiable)
        if vat:
            partner = Partner.search([
                ('vat', '=', vat),
                ('company_id', 'in', [False, company.id]),
            ], limit=1)
        # 2) Match por email exacto
        if not partner and email:
            partner = Partner.search([
                ('email', '=ilike', email),
                ('company_id', 'in', [False, company.id]),
            ], limit=1)
        # 3) Match por phone SOLO si el LLM lo pasó explícito Y no hay vat/email/name
        # (si hay vat/name pero no encontró por vat → tratamos como cliente
        # nuevo, NO fallback a phone para evitar mezclar identidades).
        if not partner and phone and not vat and not email and not name:
            partner = Partner.search([
                ('phone', '=', phone),
                ('company_id', 'in', [False, company.id]),
            ], limit=1) or Partner.search([
                ('mobile', '=', phone),
                ('company_id', 'in', [False, company.id]),
            ], limit=1)

        created = False
        if not partner:
            if not (name or vat or email):
                return {
                    'found': False,
                    'note': 'No encontrado y no hay datos para crear '
                            '(necesita nombre, vat o email).',
                }
            # Para mobile del partner nuevo: usar wa_from de la sesión
            # (es el celular real del cliente). Si el LLM pasó phone explícito,
            # priorizar ese.
            new_mobile = phone or (session.wa_from if session else False)
            partner = Partner.create({
                'name': name or vat or 'Cliente WhatsApp',
                'vat': vat or False,
                'email': email or False,
                'mobile': new_mobile or False,
                'company_id': company.id,
                'comment': 'Origen: agente WhatsApp',
            })
            created = True
            _logger.info(
                'identificar_cliente: partner CREADO id=%s name=%s vat=%s',
                partner.id, partner.name, partner.vat,
            )

        # SIEMPRE actualizar session.partner_id al partner actual (no solo si
        # estaba vacío). Permite que el cliente cambie de identidad en la
        # misma sesión.
        if session:
            if session.partner_id.id != partner.id:
                _logger.info(
                    'identificar_cliente: session %s partner %s → %s',
                    session.id, session.partner_id.id, partner.id,
                )
            session.partner_id = partner.id
            if session.state == 'nueva':
                session.action_set_state('identificando_cliente')

        return {
            'found': not created,
            'created': created,
            'partner_id': partner.id,
            'name': partner.name,
            'vat': partner.vat or '',
            'email': partner.email or '',
        }

    # -------------------------------------------------------------------------
    # Tool 5: reservar_turno → primitives.reserve_existing
    # -------------------------------------------------------------------------

    @api.model
    def reservar_turno(self, params, session=None):
        params = params or {}
        company = self._company(session)

        partner_id = params.get('partner_id') or (
            session.partner_id.id if session and session.partner_id else None)
        if not partner_id:
            return {
                'error': 'Falta partner_id. Identificá al cliente primero '
                         'con identificar_cliente.',
            }

        Primitives = self.env['innatum.agenda.scheduling.primitives']
        result = Primitives.reserve_existing(
            turno_id=params.get('turno_id'),
            partner_id=partner_id,
            servicio_code=params.get('servicio_code'),
            motivo=params.get('motivo'),
            company=company,
        )

        if result.get('exito') and session:
            session.turno_id = result['turno_id']
            # Limpiar contexto efímero del fast-path: ya no estamos en medio
            # de un flujo de reserva (el turno se confirmó).
            session.pending_turno_id = False
            session.current_servicio_code = False
            profile = self.env['innatum.business.profile'].sudo().search([
                ('company_id', '=', company.id),
            ], limit=1)
            if profile and profile.payment_policy and profile.payment_policy != 'sin_cobro':
                session.action_set_state('pendiente_pago')
            else:
                session.action_set_state('confirmada')

        return result

    # -------------------------------------------------------------------------
    # Tool: consultar_mis_citas → devuelve citas activas de un partner
    # -------------------------------------------------------------------------

    @api.model
    def consultar_mis_citas(self, params, session=None):
        """Devuelve las citas (activas o todas) del partner indicado.

        Args (params):
          partner_id: cliente. Si no, usa session.partner_id.
          solo_activas: bool default True. Si False, devuelve también las
                        terminadas (done/cancelled).

        Returns:
          {
            'count': int,
            'partner_id': int,
            'citas': [
              {'turno_id', 'referencia', 'fecha', 'fecha_iso', 'hora',
               'servicio', 'professional', 'state', 'state_label',
               'puede_cancelar': bool, 'horas_hasta_cita': float}
            ]
          }
        """
        params = params or {}
        company = self._company(session)
        partner_id = params.get('partner_id') or (
            session.partner_id.id if session and session.partner_id else None)
        if not partner_id:
            return {'error': 'partner_id requerido'}

        solo_activas = params.get('solo_activas', True)
        states = ('reserved', 'confirmed') if solo_activas else (
            'reserved', 'confirmed', 'done', 'cancelled')

        Turno = self.env['innatum.agenda.turno'].sudo()
        turnos = Turno.search([
            ('partner_id', '=', int(partner_id)),
            ('state', 'in', list(states)),
            ('company_id', '=', company.id),
        ], order='date_start asc')

        # Política de cancelación
        profile = self.env['innatum.business.profile'].sudo().search([
            ('company_id', '=', company.id),
        ], limit=1)
        min_notice_h = (profile.min_cancellation_notice_hours
                        if profile and profile.allows_cancellation else 0)
        allows = bool(profile and profile.allows_cancellation)

        import pytz
        from datetime import datetime
        tz = pytz.timezone('America/Guayaquil')
        now = datetime.now(tz)

        state_labels = {
            'reserved': 'Reservada (pendiente confirmar)',
            'confirmed': 'Confirmada',
            'done': 'Finalizada',
            'cancelled': 'Cancelada',
        }

        citas = []
        for t in turnos:
            dt_local = pytz.UTC.localize(t.date_start).astimezone(tz)
            horas_hasta = (dt_local - now).total_seconds() / 3600
            puede_cancelar = (
                allows
                and t.state in ('reserved', 'confirmed')
                and horas_hasta > min_notice_h
            )
            citas.append({
                'turno_id': t.id,
                'referencia': t.name,
                'fecha': _fecha_es(dt_local),
                'fecha_iso': dt_local.strftime('%Y-%m-%d'),
                'hora': dt_local.strftime('%H:%M'),
                'servicio': (t.servicio_id.name if t.servicio_id else '') or
                            (t.servicio_ids[:1].name if t.servicio_ids else ''),
                'professional': t.professional_id.name,
                'state': t.state,
                'state_label': state_labels.get(t.state, t.state),
                'puede_cancelar': puede_cancelar,
                'horas_hasta_cita': round(horas_hasta, 1),
            })

        return {
            'count': len(citas),
            'partner_id': int(partner_id),
            'citas': citas,
            'allows_cancellation': allows,
            'min_cancellation_notice_hours': min_notice_h,
        }

    # -------------------------------------------------------------------------
    # Tool: cancelar_turno → cancela un turno respetando las reglas del negocio
    # -------------------------------------------------------------------------

    @api.model
    def cancelar_turno(self, params, session=None):
        """Cancela un turno aplicando reglas del business_profile.

        Args:
          turno_id: ID del turno a cancelar (obligatorio).
          motivo: nota interna opcional.

        Reglas:
          - business_profile.allows_cancellation debe ser True.
          - business_profile.min_cancellation_notice_hours debe respetarse
            (turno debe estar al menos N horas en el futuro).
          - El turno debe ser del partner que está en sesión (anti-abuso).
          - El turno debe estar en state reserved o confirmed.
        """
        params = params or {}
        company = self._company(session)
        turno_id = params.get('turno_id')
        if not turno_id:
            return {'error': 'turno_id requerido'}

        Turno = self.env['innatum.agenda.turno'].sudo()
        turno = Turno.browse(int(turno_id))
        if not turno.exists() or turno.company_id.id != company.id:
            return {'error': 'Turno no encontrado o no pertenece a este negocio.'}

        # Validar propiedad del turno (debe ser del partner de la sesión).
        # SIN identidad NO se cancela: la ausencia de partner_id es motivo de
        # denegación, nunca de permiso (antes se saltaba la comprobación
        # entera y una sesión sin identificar podía cancelar citas ajenas).
        if session:
            if not session.partner_id:
                return {'error': 'Necesito identificarte antes de cancelar '
                                 'una cita.'}
            if turno.partner_id.id != session.partner_id.id:
                return {'error': 'Este turno no pertenece a tu cuenta.'}

        if turno.state not in ('reserved', 'confirmed'):
            return {
                'error': f'No se puede cancelar un turno en estado '
                         f'{turno.state}. Solo se cancelan reservados o '
                         f'confirmados.',
            }

        # Reglas del business_profile
        profile = self.env['innatum.business.profile'].sudo().search([
            ('company_id', '=', company.id),
        ], limit=1)
        if profile and not profile.allows_cancellation:
            return {
                'error': 'El negocio no permite cancelación por este canal. '
                         'Contacta directamente.',
            }
        min_notice_h = (profile.min_cancellation_notice_hours
                        if profile else 24)

        import pytz
        from datetime import datetime
        tz = pytz.timezone('America/Guayaquil')
        now = datetime.now(tz)
        dt_local = pytz.UTC.localize(turno.date_start).astimezone(tz)
        horas_hasta = (dt_local - now).total_seconds() / 3600

        if horas_hasta < min_notice_h:
            if horas_hasta < 0:
                detalle = 'la cita ya pasó o está en curso'
            else:
                detalle = f'faltan {round(horas_hasta, 1)}h'
            return {
                'error': f'No es posible cancelar con menos de {min_notice_h}h '
                         f'de anticipación ({detalle}).',
                'requires_human': True,
            }

        # Ejecutar cancelación
        motivo = (params.get('motivo') or '').strip()
        notes = f'[Cancelado por cliente vía WhatsApp]'
        if motivo:
            notes += f' Motivo: {motivo}'
        try:
            if motivo or not turno.notes:
                turno.notes = (turno.notes or '') + '\n' + notes
            turno.action_cancel()
        except Exception as exc:
            _logger.exception('cancelar_turno crashed turno_id=%s', turno_id)
            return {'error': f'Error al cancelar: {exc}'}

        return {
            'ok': True,
            'turno_id': turno.id,
            'referencia': turno.name,
            'fecha': _fecha_es(dt_local),
            'hora': dt_local.strftime('%H:%M'),
            'mensaje': '¡Cita cancelada exitosamente!',
        }

    # -------------------------------------------------------------------------
    # Tool 6: solicitar_handoff — específico de WhatsApp
    # -------------------------------------------------------------------------

    @api.model
    def solicitar_handoff(self, params, session=None):
        """Marca la sesión como con_humano y deja una nota.

        En Fase 1B solo logueamos. Fase 2 dispara notification_dispatcher
        (panel Odoo + WhatsApp personal + email).
        """
        if not session:
            return {'error': 'session no provista'}
        params = params or {}
        motivo = params.get('motivo') or 'No especificado'
        urgencia = params.get('urgencia') or 'normal'

        previous_state = session.state
        session.action_set_state('con_humano')
        session.append_message(
            role='system',
            content=f'[HANDOFF SOLICITADO] motivo={motivo}, urgencia={urgencia}, '
                    f'estado_previo={previous_state}',
        )
        _logger.info(
            'Handoff requested on session %s: motivo=%s urgencia=%s',
            session.id, motivo, urgencia)
        return {
            'ok': True,
            'session_state': session.state,
            'previous_state': previous_state,
            'message_for_client': 'Te paso con una persona del equipo; '
                                  'en breve te responderá.',
        }

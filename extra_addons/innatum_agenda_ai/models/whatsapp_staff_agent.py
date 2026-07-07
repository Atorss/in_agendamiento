# -*- coding: utf-8 -*-
"""Agente WhatsApp para STAFF (colaboradores del tenant) — Fase 2.

Máquina de estados determinista (menús, listas y botones, SIN LLM) para
que un colaborador atienda sus derivaciones respondiendo el WhatsApp:
ver pendientes → proponer horarios (huecos libres reales) → confirmar.
El contrato de salida es idéntico al del agente de pacientes
(response_text / meta_payload / session_state / fast_path).
"""
import logging
import re
from datetime import datetime, timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

_RE_ST_DERIV = re.compile(r'^st_deriv:(\d+)$')
_RE_ST_SLOT = re.compile(r'^st_slot:(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})$')

SLOTS_PER_PAGE = 9   # 9 huecos + fila "Ver más" = 10 (límite Meta)
DIAS_VENTANA = 21    # mismo horizonte que el planificador visual


class WhatsappStaffAgent(models.AbstractModel):
    _name = 'innatum.whatsapp.staff.agent'
    _description = 'WhatsApp Staff Agent (derivaciones)'

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    @api.model
    def process_staff_message(self, session, text):
        """Despacha el mensaje de un empleado. El router del agente de
        pacientes ya persistió el mensaje entrante y validó el wamid."""
        text = (text or '').strip()
        try:
            m = _RE_ST_DERIV.match(text)
            if m:
                return self._abrir_derivacion(session, int(m.group(1)))
            m = _RE_ST_SLOT.match(text)
            if m:
                return self._agregar_propuesta(session, m.group(1))
            if text == 'st_more':
                session.staff_slot_page += 1
                return self._mostrar_slots(session)
            if text == 'st_addmore':
                return self._mostrar_slots(session)
            if text == 'st_confirm':
                return self._confirmar(session)
            if text == 'st_cancel':
                return self._cancelar(session)
            return self._menu(session)
        except Exception:  # el agente staff jamás rompe el webhook
            _logger.exception('Staff agent crashed (session=%s)', session.id)
            return self._text(session, 'Ocurrió un error inesperado. Escribe '
                                       'cualquier mensaje para volver al menú.')

    # ------------------------------------------------------------------
    # Menú (los métodos de slots/confirmación se agregan en Tasks 3-4)
    # ------------------------------------------------------------------

    def _menu(self, session):
        emp = session.employee_id
        session.write({'staff_derivacion_id': False, 'staff_slot_page': 0})
        session.action_set_state('staff_menu')
        pendientes = self._derivaciones_pendientes(session)
        nombre = (emp.name or '').split(' ')[0]
        if not pendientes:
            return self._text(session, (
                '¡Hola %s! 👋 No tienes derivaciones pendientes de agendar. '
                'Cuando un colega te derive un paciente, te avisaré por aquí.'
            ) % nombre)
        if len(pendientes) == 1:
            return self._abrir_derivacion(session, pendientes.id)
        Agent = self.env['innatum.whatsapp.agent']
        rows = [{
            'id': 'st_deriv:%d' % d.id,
            'title': (d.partner_id.name or 'Paciente')[:24],
            'description': '%s · derivó %s' % (
                d.servicio_id.name or '-', d.derivado_por_id.name or '-'),
        } for d in pendientes[:10]]
        body = ('¡Hola %s! 👋 Tienes %d derivaciones pendientes. '
                'Elige una para proponer horarios:') % (
            nombre, len(pendientes))
        payload = Agent._payload_list(
            session.wa_from, header='📋 Derivaciones', body=body,
            button_text='Ver derivaciones',
            sections=[{'title': 'Pendientes', 'rows': rows}])
        return self._resp(session, body, payload, 'staff_menu')

    def _derivaciones_pendientes(self, session):
        return self.env['innatum.agenda.turno'].sudo().search([
            ('company_id', '=', session.company_id.id),
            ('es_derivacion', '=', True),
            ('state', '=', 'derivado'),
            ('professional_id', '=', session.employee_id.id),
        ], order='create_date')

    def _abrir_derivacion(self, session, deriv_id):
        """Se implementa completo en Task 3; aquí versión mínima que fija
        el contexto y delega en _mostrar_slots (Task 3)."""
        deriv = self.env['innatum.agenda.turno'].sudo().browse(
            deriv_id).exists()
        if not deriv or deriv.state != 'derivado' \
                or deriv.professional_id != session.employee_id:
            return self._text(session, 'Esa derivación ya no está pendiente. '
                                       'Escribe cualquier mensaje para ver '
                                       'tu lista actualizada.')
        session.write({'staff_derivacion_id': deriv.id, 'staff_slot_page': 0})
        session.action_set_state('staff_derivacion')
        return self._mostrar_slots(session)

    def _mostrar_slots(self, session, aviso=None):
        """Lista interactiva con los huecos libres del colaborador para la
        derivación en curso (9 por página + 'Ver más')."""
        deriv = session.staff_derivacion_id
        if not deriv or deriv.state != 'derivado':
            return self._menu(session)
        session.action_set_state('staff_proponiendo')
        Agent = self.env['innatum.whatsapp.agent']
        slots = self._slots_libres(deriv)
        page = session.staff_slot_page
        chunk = slots[page * SLOTS_PER_PAGE:(page + 1) * SLOTS_PER_PAGE]
        if not chunk and page:
            page = session.staff_slot_page = 0
            chunk = slots[:SLOTS_PER_PAGE]
        n_prop = len(deriv.propuesta_ids)
        if not chunk:
            if n_prop:
                return self._botones_propuesta(session, deriv, (
                    'No hay más huecos libres en los próximos %d días.'
                ) % DIAS_VENTANA)
            return self._text(session, (
                'No encontré huecos libres en tus próximos %d días para '
                '%s. Revisa tu planificación en el sistema.'
            ) % (DIAS_VENTANA, deriv.servicio_id.name or 'este servicio'))
        rows = [{
            'id': 'st_slot:%s' % dt.strftime('%Y-%m-%d %H:%M:%S'),
            'title': Agent._fmt_dt_ec(dt),
            'description': '',
        } for dt in chunk]
        if len(slots) > (page + 1) * SLOTS_PER_PAGE:
            rows.append({'id': 'st_more', 'title': '➡️ Ver más fechas',
                         'description': ''})
        motivo = ('\nMotivo: %s' % deriv.motivo_derivacion
                  if deriv.motivo_derivacion else '')
        body = ('Derivación de *%s* (%s), derivada por %s.%s\n'
                'Elige un horario para proponer:') % (
            deriv.partner_id.name or '-', deriv.servicio_id.name or '-',
            deriv.derivado_por_id.name or '-', motivo)
        if n_prop:
            body = ('Llevas %d horario(s) propuesto(s).\n' % n_prop) + body
        if aviso:
            body = aviso + '\n' + body
        payload = Agent._payload_list(
            session.wa_from, header='📅 Proponer horarios', body=body,
            button_text='Ver horarios',
            sections=[{'title': 'Huecos libres', 'rows': rows}])
        return self._resp(session, body, payload, 'staff_slots')

    def _slots_libres(self, deriv):
        """Inicios de hueco libres del colaborador (UTC naive), descontando
        turnos, bloqueos y los horarios YA propuestos de esta derivación."""
        Avail = self.env['innatum.agenda.availability']
        ahora = datetime.utcnow()
        dur = int(deriv.duracion_override
                  or (deriv.servicio_id.duracion if deriv.servicio_id else 0)
                  or 30)
        slots = Avail.free_slots(
            deriv.professional_id, deriv.servicio_id,
            ahora, ahora + timedelta(days=DIAS_VENTANA),
            duration_min=dur, granularity_min=dur)
        propuestos = set(deriv.propuesta_ids.mapped('date_start'))
        return [s for s in slots if s not in propuestos]

    def _agregar_propuesta(self, session, dt_str):
        """Tap en un hueco: crea la propuesta real (las constraints del core
        validan solape y pasado). El savepoint garantiza que una propuesta
        inválida NO quede persistida (create inserta antes de que corran
        las constraints). El guard de duplicado cubre el re-tap de la misma
        fila de la lista (que sigue visible en el chat)."""
        deriv = session.staff_derivacion_id
        if not deriv or deriv.state != 'derivado':
            return self._menu(session)
        dt = fields.Datetime.to_datetime(dt_str)
        if dt in deriv.propuesta_ids.mapped('date_start'):
            return self._botones_propuesta(
                session, deriv, 'Ese horario ya está en tus propuestas.')
        try:
            with self.env.cr.savepoint():
                self.env['innatum.agenda.turno.propuesta'].sudo().create({
                    'derivacion_id': deriv.id,
                    'tipo': 'propuesta',
                    'date_start': dt,
                })
        except ValidationError:
            session.staff_slot_page = 0
            return self._mostrar_slots(
                session, aviso='⚠️ Ese horario ya no está libre. Elige otro:')
        Agent = self.env['innatum.whatsapp.agent']
        return self._botones_propuesta(
            session, deriv, '✅ Agregado: %s.' % Agent._fmt_dt_ec(dt))

    def _botones_propuesta(self, session, deriv, encabezado):
        Agent = self.env['innatum.whatsapp.agent']
        n = len(deriv.propuesta_ids)
        body = ('%s\nLlevas %d horario(s) propuesto(s) para %s. '
                '¿Agregas otro o confirmas?') % (
            encabezado, n, deriv.partner_id.name or '-')
        payload = Agent._payload_buttons(
            session.wa_from, header='📅 Propuestas', body=body,
            buttons=[
                {'id': 'st_addmore', 'title': '➕ Otra fecha'},
                {'id': 'st_confirm', 'title': '✅ Confirmar (%d)' % n},
                {'id': 'st_cancel', 'title': '✖ Cancelar'},
            ])
        return self._resp(session, body, payload, 'staff_propuesta')

    def _confirmar(self, session):
        deriv = session.staff_derivacion_id
        if not deriv or deriv.state != 'derivado' \
                or deriv.professional_id != session.employee_id:
            return self._menu(session)
        if not deriv.propuesta_ids:
            return self._mostrar_slots(session, aviso=(
                'Aún no has propuesto ningún horario. Elige al menos uno:'))
        n = len(deriv.propuesta_ids)
        try:
            deriv.action_confirmar_derivacion()
        except UserError as exc:
            return self._text(session, '⚠️ %s' % (
                exc.args[0] if exc.args else exc))
        body = ('✅ Listo: propusiste %d horario(s) para %s. Le enviamos '
                'las opciones al paciente para que elija; te avisaré '
                'cuando quede agendado.') % (n, deriv.partner_id.name or '-')
        session.write({'staff_derivacion_id': False, 'staff_slot_page': 0})
        session.action_set_state('staff_menu')
        return self._text(session, body)

    def _cancelar(self, session):
        deriv = session.staff_derivacion_id
        if deriv:
            self.env['innatum.agenda.turno.propuesta'].sudo().search([
                ('derivacion_id', '=', deriv.id)]).unlink()
        session.write({'staff_derivacion_id': False, 'staff_slot_page': 0})
        session.action_set_state('staff_menu')
        return self._text(session, 'Descarté las propuestas. Escribe '
                                   'cualquier mensaje para ver tus '
                                   'derivaciones pendientes.')

    # ------------------------------------------------------------------
    # Helpers de respuesta
    # ------------------------------------------------------------------

    def _text(self, session, body):
        return self._resp(session, body, None, 'staff_text')

    def _resp(self, session, body, payload, fast_path):
        session.append_message(role='assistant', content=body)
        return {
            'response_text': body,
            'session_state': session.state,
            'tool_calls': [],
            'meta_payload': payload,
            'fast_path': fast_path,
        }

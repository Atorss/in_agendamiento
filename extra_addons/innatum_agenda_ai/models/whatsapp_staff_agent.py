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
from datetime import datetime, time, timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from .staff_date_parser import EC_OFFSET, parse_fecha_escrita

_logger = logging.getLogger(__name__)

_RE_ST_DERIV = re.compile(r'^st_deriv:(\d+)$')
_RE_ST_SLOT = re.compile(r'^st_slot:(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})$')
_RE_ST_DAY = re.compile(r'^st_day:(\d{4}-\d{2}-\d{2})$')

DIAS_PER_PAGE = 9    # 9 días + 'Más días' = 10 filas (límite Meta)
HORAS_PER_PAGE = 8   # 8 horas + 'Más horas' + 'Otros días' = 10
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
            m = _RE_ST_DAY.match(text)
            if m:
                session.write({'staff_dia': m.group(1),
                               'staff_slot_page': 0})
                return self._mostrar_horas(session)
            if text in ('st_dmore', 'st_more'):   # st_more: listas viejas
                session.staff_slot_page += 1
                return self._mostrar_dias(session)
            if text == 'st_hmore':
                session.staff_slot_page += 1
                return self._mostrar_horas(session)
            if text in ('st_days', 'st_addmore'):
                session.write({'staff_dia': False, 'staff_slot_page': 0})
                return self._mostrar_dias(session)
            if text == 'st_confirm':
                return self._confirmar(session)
            if text == 'st_cancel':
                return self._cancelar(session)
            if session.state in ('staff_derivacion', 'staff_proponiendo') \
                    and session.staff_derivacion_id:
                return self._procesar_fecha_escrita(session, text)
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
        session.write({'staff_derivacion_id': False, 'staff_slot_page': 0,
                       'staff_dia': False})
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
        """Fija el contexto de la derivación y muestra la lista de días
        con disponibilidad (_mostrar_dias)."""
        deriv = self.env['innatum.agenda.turno'].sudo().browse(
            deriv_id).exists()
        if not deriv or deriv.state != 'derivado' \
                or deriv.professional_id != session.employee_id:
            return self._text(session, 'Esa derivación ya no está pendiente. '
                                       'Escribe cualquier mensaje para ver '
                                       'tu lista actualizada.')
        session.write({'staff_derivacion_id': deriv.id,
                       'staff_slot_page': 0, 'staff_dia': False})
        session.action_set_state('staff_derivacion')
        return self._mostrar_dias(session)

    def _dias_disponibles(self, deriv):
        """[(date_local, n_huecos)] ordenado; solo días con huecos."""
        conteo = {}
        for dt in self._slots_libres(deriv):
            d = (dt - EC_OFFSET).date()
            conteo[d] = conteo.get(d, 0) + 1
        return sorted(conteo.items())

    def _fmt_dia_ec(self, d):
        """'mié 15 jul' — reusa _fmt_dt_ec ('mié 15 jul · 10:00')."""
        Agent = self.env['innatum.whatsapp.agent']
        dt_utc = datetime.combine(d, time(12, 0)) + EC_OFFSET
        return Agent._fmt_dt_ec(dt_utc).split(' · ')[0]

    def _mostrar_dias(self, session, aviso=None):
        """Nivel 1: lista de días con disponibilidad (9 + Más días)."""
        deriv = session.staff_derivacion_id
        if not deriv or deriv.state != 'derivado':
            return self._menu(session)
        session.action_set_state('staff_proponiendo')
        if session.staff_dia:
            # Bajamos de nivel (horas -> días): staff_slot_page es
            # compartida por ambos niveles, así que debe resetear junto
            # con staff_dia. Si YA estábamos en días (staff_dia vacío),
            # se preserva la página actual (paginación de días).
            session.write({'staff_dia': False, 'staff_slot_page': 0})
        Agent = self.env['innatum.whatsapp.agent']
        dias = self._dias_disponibles(deriv)
        page = session.staff_slot_page
        chunk = dias[page * DIAS_PER_PAGE:(page + 1) * DIAS_PER_PAGE]
        if not chunk and page:
            page = session.staff_slot_page = 0
            chunk = dias[:DIAS_PER_PAGE]
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
            'id': 'st_day:%s' % d.strftime('%Y-%m-%d'),
            'title': self._fmt_dia_ec(d)[:24],
            'description': '%d horario(s) libre(s)' % n,
        } for d, n in chunk]
        if len(dias) > (page + 1) * DIAS_PER_PAGE:
            rows.append({'id': 'st_dmore', 'title': '➡️ Más días',
                         'description': ''})
        motivo = ('\nMotivo: %s' % deriv.motivo_derivacion
                  if deriv.motivo_derivacion else '')
        body = ('Derivación de *%s* (%s), derivada por %s.%s\n'
                'Elige un día — o escríbeme la fecha y hora '
                '(ej: "mañana 15:00" o "15/07 10:00").') % (
            deriv.partner_id.name or '-', deriv.servicio_id.name or '-',
            deriv.derivado_por_id.name or '-', motivo)
        if n_prop:
            body = ('Llevas %d horario(s) propuesto(s).\n' % n_prop) + body
        if aviso:
            body = aviso + '\n' + body
        payload = Agent._payload_list(
            session.wa_from, header='📅 Proponer horarios', body=body,
            button_text='Ver días',
            sections=[{'title': 'Días con horarios', 'rows': rows}])
        return self._resp(session, body, payload, 'staff_dias')

    def _mostrar_horas(self, session, aviso=None):
        """Nivel 2: horas libres del día en contexto (8 + Más horas +
        Otros días). Sin día o día ya sin huecos → vuelve a los días."""
        deriv = session.staff_derivacion_id
        if not deriv or deriv.state != 'derivado':
            return self._menu(session)
        dia = session.staff_dia
        if not dia:
            return self._mostrar_dias(session, aviso=aviso)
        session.action_set_state('staff_proponiendo')
        Agent = self.env['innatum.whatsapp.agent']
        slots = [dt for dt in self._slots_libres(deriv)
                 if (dt - EC_OFFSET).date() == dia]
        if not slots:
            session.write({'staff_dia': False, 'staff_slot_page': 0})
            extra = 'Ese día no tiene horarios libres. Elige otro:'
            return self._mostrar_dias(
                session, aviso=(aviso + '\n' + extra) if aviso else extra)
        page = session.staff_slot_page
        chunk = slots[page * HORAS_PER_PAGE:(page + 1) * HORAS_PER_PAGE]
        if not chunk and page:
            page = session.staff_slot_page = 0
            chunk = slots[:HORAS_PER_PAGE]
        rows = [{
            'id': 'st_slot:%s' % dt.strftime('%Y-%m-%d %H:%M:%S'),
            'title': Agent._fmt_dt_ec(dt).split(' · ')[1],
            'description': '',
        } for dt in chunk]
        if len(slots) > (page + 1) * HORAS_PER_PAGE:
            rows.append({'id': 'st_hmore', 'title': '➡️ Más horas',
                         'description': ''})
        rows.append({'id': 'st_days', 'title': '⬅️ Otros días',
                     'description': ''})
        body = '%s — horarios libres para %s:' % (
            self._fmt_dia_ec(dia), deriv.partner_id.name or '-')
        if aviso:
            body = aviso + '\n' + body
        payload = Agent._payload_list(
            session.wa_from, header='📅 Elige la hora', body=body,
            button_text='Ver horarios',
            sections=[{'title': 'Horas libres', 'rows': rows}])
        return self._resp(session, body, payload, 'staff_horas')

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
            session.write({
                'staff_dia': (dt - EC_OFFSET).date(),
                'staff_slot_page': 0,
            })
            return self._mostrar_horas(
                session, aviso='⚠️ Ese horario ya no está libre. Elige otro:')
        Agent = self.env['innatum.whatsapp.agent']
        return self._botones_propuesta(
            session, deriv, '✅ Agregado: %s.' % Agent._fmt_dt_ec(dt))

    def _procesar_fecha_escrita(self, session, text):
        """Texto libre dentro de una derivación: intenta fecha escrita.

        Parsea → valida pasado/ventana → valida hueco libre (mismo
        cálculo que las listas) → agrega por el camino del tap. Cada
        rechazo explica el motivo y relista (días u horas del día)."""
        deriv = session.staff_derivacion_id
        if not deriv or deriv.state != 'derivado':
            return self._menu(session)
        ahora = datetime.utcnow()
        dt = parse_fecha_escrita(text, ahora,
                                 dia_contexto=session.staff_dia)
        if dt is None:
            return self._mostrar_dias(session, aviso=(
                'No logré entender esa fecha 🤔. Escríbela como '
                '"mañana 15:00" o "15/07 10:00" — o elige de la lista:'))
        if dt <= ahora:
            return self._mostrar_dias(session, aviso=(
                '⚠️ Esa fecha ya pasó. Elige una futura:'))
        if dt > ahora + timedelta(days=DIAS_VENTANA):
            return self._mostrar_dias(session, aviso=(
                '⚠️ Solo agendo dentro de los próximos %d días. '
                'Elige una fecha más cercana:') % DIAS_VENTANA)
        if dt in self._slots_libres(deriv):
            session.write({'staff_dia': (dt - EC_OFFSET).date(),
                           'staff_slot_page': 0})
            return self._agregar_propuesta(
                session, dt.strftime('%Y-%m-%d %H:%M:%S'))
        # Parseó pero no es hueco libre (ocupado, fuera de jornada,
        # bloqueado o ya propuesto): mostrar lo libre de ese día.
        session.write({'staff_dia': (dt - EC_OFFSET).date(),
                       'staff_slot_page': 0})
        return self._mostrar_horas(session, aviso=(
            '⚠️ Ese horario no está disponible. Lo libre de ese día:'))

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
            return self._mostrar_dias(session, aviso=(
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
        session.write({'staff_derivacion_id': False, 'staff_slot_page': 0,
                       'staff_dia': False})
        session.action_set_state('staff_menu')
        return self._text(session, body)

    def _cancelar(self, session):
        deriv = session.staff_derivacion_id
        if deriv:
            self.env['innatum.agenda.turno.propuesta'].sudo().search([
                ('derivacion_id', '=', deriv.id)]).unlink()
        session.write({'staff_derivacion_id': False, 'staff_slot_page': 0,
                       'staff_dia': False})
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

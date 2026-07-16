# -*- coding: utf-8 -*-
"""Agente de pantallas del Flow de agendamiento (Flows-1).

Determinista, sin LLM. Recibe payloads YA descifrados (el transporte y
la criptografía viven en el controller) y responde el dict en claro
{'screen', 'data'} que el controller cifra. El estado del funnel viaja
por eco en `data` (servicio_code, slot_id) — el endpoint es stateless
salvo la vinculación de partner a la sesión. Spec §5."""
import logging
from datetime import datetime, timedelta

from odoo import api, models

from .cedula_validator import extract_cedula, validate_ec_cedula
from .staff_date_parser import EC_OFFSET

_logger = logging.getLogger(__name__)

DIAS_VENTANA = 21


class InnatumWaFlowAgent(models.AbstractModel):
    _name = 'innatum.wa.flow.agent'
    _description = 'WhatsApp Flow Agent (agendamiento del paciente)'

    @api.model
    def handle(self, session, action, screen, data, flow_token):
        try:
            if action == 'ping':
                return {'data': {'status': 'active'}}
            if action == 'INIT':
                return self._init(session)
            if action == 'BACK':
                return self._handle_back(session, screen, data)
            if action == 'data_exchange':
                if screen == 'SERVICIO':
                    return self._screen_fecha(session,
                                              data.get('servicio_code'))
                if screen == 'FECHA':
                    return self._screen_hora(session, data)
                if screen == 'HORA':
                    return self._post_hora(session, data)
                if screen == 'IDENTIDAD':
                    return self._identidad(session, data)
                if screen == 'CONFIRMAR':
                    return self._reservar(session, data, flow_token)
            return self._error_sesion()
        except Exception:
            _logger.exception('Flow agent crashed (session=%s, screen=%s)',
                              session.id, screen)
            return self._error_sesion(
                'Ocurrió un error. Cierra esta ventana y escribe *hola*.')

    # ------------------------------------------------------------------

    def _handle_back(self, session, screen, data):
        """BACK re-renderiza la pantalla a la que el usuario vuelve (con
        `refresh_on_back`), usando el mismo builder que la deja allí por
        primera vez — NUNCA reinicia el funnel salvo que la pantalla de
        destino sea desconocida. Antes esto mapeaba a `_init` para
        cualquier `screen`, devolviendo FECHA/SERVICIO cuando el cliente
        volvía a HORA."""
        if screen == 'FECHA':
            return self._screen_fecha(session, data.get('servicio_code'))
        if screen == 'HORA':
            return self._screen_hora(session, data)
        if screen == 'SERVICIO':
            return self._init(session)
        if screen in ('IDENTIDAD', 'CONFIRMAR'):
            return self._post_hora(session, data)
        return self._init(session)

    def _error_sesion(self, msg=None):
        return {'screen': 'ERROR_SESION', 'data': {'mensaje': msg or (
            'Tu sesión expiró. Cierra esta ventana y escribe *hola* '
            'para agendar.')}}

    def _servicios_publicados(self, company):
        return self.env['innatum.agenda.servicio'].sudo().search([
            ('company_id', '=', company.id),
            ('publicar_web', '=', True),
        ]).filtered('operador_ids')

    def _init(self, session):
        # INIT SIEMPRE devuelve la pantalla de ENTRADA (SERVICIO), aunque
        # haya un solo servicio. El Flow PUBLICADO exige que el INIT
        # inicialice la pantalla de entrada (la única sin aristas entrantes
        # del routing_model). Saltar a FECHA con 1 servicio rompía el Flow
        # publicado ("Se produjo un error"); en borrador Meta lo toleraba.
        # Con un solo servicio el paciente ve una única opción y toca
        # Continuar (SERVICIO→FECHA por data_exchange, que sí funciona).
        servicios = self._servicios_publicados(session.company_id)
        if not servicios:
            return self._error_sesion(
                'No hay servicios disponibles. Escribe *hola* en el chat.')
        return {'screen': 'SERVICIO', 'data': {
            'servicios': [{'id': s.code, 'title': s.name}
                          for s in servicios],
            'error_message': '',
            'has_error': False,
        }}

    def _resolver_servicio(self, session, servicio_code):
        return self.env['innatum.agenda.servicio'].sudo().search([
            ('company_id', '=', session.company_id.id),
            ('code', '=', servicio_code or ''),
        ], limit=1)

    def _slots_de(self, servicio):
        """[(dt_utc, employee)] libres en la ventana, todos los operadores."""
        Av = self.env['innatum.agenda.availability'].sudo()
        dur = int(servicio.duracion or 30)
        dt_from = datetime.utcnow()
        dt_to = dt_from + timedelta(days=DIAS_VENTANA)
        out = []
        for op in servicio.operador_ids.filtered('active'):
            for st in Av.free_slots(op, servicio, dt_from, dt_to,
                                    duration_min=dur, granularity_min=dur):
                out.append((st, op))
        out.sort(key=lambda x: x[0])
        return out

    def _screen_fecha(self, session, servicio_code, aviso=''):
        servicio = self._resolver_servicio(session, servicio_code)
        if not servicio:
            # Eco roto a mitad de flujo: NO reiniciamos a SERVICIO (la
            # pantalla de entrada no puede tener aristas entrantes en el
            # routing_model de Meta) — lo tratamos como fallo de integridad
            # de sesión y cerramos con ERROR_SESION.
            return self._error_sesion()
        hoy = (datetime.utcnow() - EC_OFFSET).date()
        max_d = hoy + timedelta(days=DIAS_VENTANA)
        con_hueco = {(dt - EC_OFFSET).date()
                     for dt, _op in self._slots_de(servicio)}
        unavailable = []
        d = hoy
        while d <= max_d:
            if d not in con_hueco:
                unavailable.append(d.strftime('%Y-%m-%d'))
            d += timedelta(days=1)
        return {'screen': 'FECHA', 'data': {
            'servicio_code': servicio.code,
            'servicio_nombre': servicio.name,
            'min_date': hoy.strftime('%Y-%m-%d'),
            'max_date': max_d.strftime('%Y-%m-%d'),
            'unavailable_dates': unavailable,
            'error_message': aviso,
            'has_error': bool(aviso),
        }}

    def _screen_hora(self, session, data, aviso=''):
        servicio = self._resolver_servicio(session, data.get('servicio_code'))
        fecha = data.get('fecha') or ''
        if not servicio or not fecha:
            # Eco roto a mitad de flujo → ERROR_SESION (ver _screen_fecha).
            return self._error_sesion()
        slots = [(dt, op) for dt, op in self._slots_de(servicio)
                 if (dt - EC_OFFSET).date().strftime('%Y-%m-%d') == fecha]
        if not slots:
            return self._screen_fecha(
                session, servicio.code,
                aviso='Ese día ya no tiene horarios. Elige otro.')
        Agent = self.env['innatum.whatsapp.agent']
        multi_op = len({op.id for _dt, op in slots}) > 1
        horas = []
        for dt, op in slots[:20]:
            hora = Agent._fmt_dt_ec(dt).split(' · ')[1]
            horas.append({
                'id': '%d|%s' % (op.id, dt.strftime('%Y-%m-%dT%H:%M:%S')),
                'title': ('%s · %s' % (hora, op.name)) if multi_op else hora,
            })
        return {'screen': 'HORA', 'data': {
            'servicio_code': servicio.code,
            'fecha': fecha,
            'fecha_label': Agent._fmt_dt_ec(
                slots[0][0]).split(' · ')[0],
            'horas': horas,
            'error_message': aviso,
            'has_error': bool(aviso),
        }}

    def _resolver_operador(self, session, servicio, prof_id):
        """Empleado del slot echoed SOLO si es operador del servicio en
        este tenant. Evita fuga de nombres de otros tenants por slot_id
        manipulado (el slot_id viaja por el dispositivo del cliente)."""
        try:
            pid = int(prof_id)
        except (TypeError, ValueError):
            return self.env['hr.employee'].browse()
        if not servicio:
            return self.env['hr.employee'].browse()
        return servicio.operador_ids.filtered(
            lambda e: e.id == pid and e.company_id == session.company_id
                      and e.active)

    def _resumen(self, session, data):
        servicio = self._resolver_servicio(session, data.get('servicio_code'))
        prof_id, dt_iso = (data.get('slot_id') or '|').split('|')
        emp = self._resolver_operador(session, servicio, prof_id)
        Agent = self.env['innatum.whatsapp.agent']
        dt = datetime.strptime(dt_iso, '%Y-%m-%dT%H:%M:%S') if dt_iso else None
        return '%s — %s con %s' % (
            servicio.name if servicio else '-',
            Agent._fmt_dt_ec(dt) if dt else '-',
            emp.name if emp else '-')

    def _post_hora(self, session, data):
        base = {'servicio_code': data.get('servicio_code'),
                'slot_id': data.get('slot_id'),
                'resumen': self._resumen(session, data),
                'error_message': '',
                'has_error': False}
        if session.partner_id:
            return {'screen': 'CONFIRMAR', 'data': base}
        return {'screen': 'IDENTIDAD', 'data': base}

    def _identidad(self, session, data):
        cedula = extract_cedula(data.get('cedula') or '')
        valid, err = (validate_ec_cedula(cedula) if cedula
                      else (False, 'Cédula no reconocida.'))
        nombre = (data.get('nombre') or '').strip()
        if not valid or len(nombre) < 3:
            return {'screen': 'IDENTIDAD', 'data': {
                'servicio_code': data.get('servicio_code'),
                'slot_id': data.get('slot_id'),
                'resumen': self._resumen(session, data),
                'error_message': (err if not valid else
                                  'Escribe tu nombre completo.'),
                'has_error': True,
            }}
        Partner = self.env['res.partner'].sudo()
        partner = Partner.search([
            ('vat', '=', cedula),
            ('company_id', 'in', [False, session.company_id.id]),
        ], limit=1)
        if not partner:
            partner = Partner.create({
                'name': nombre,
                'vat': cedula,
                'mobile': session.wa_from or False,
                'company_id': session.company_id.id,
                'comment': 'Origen: WhatsApp Flow',
            })
        session.partner_id = partner.id
        return self._post_hora(session, data)

    def _confirmar_con_error(self, session, data, aviso):
        """Refresca la MISMA pantalla CONFIRMAR con un aviso. El routing de
        Meta solo admite rutas hacia adelante: CONFIRMAR no puede navegar de
        vuelta a HORA/IDENTIDAD (sería backward). Ante un hueco robado el
        usuario toca *Atrás* → HORA se recalcula por `refresh_on_back`."""
        return {'screen': 'CONFIRMAR', 'data': {
            'servicio_code': data.get('servicio_code'),
            'slot_id': data.get('slot_id'),
            'resumen': self._resumen(session, data),
            'error_message': aviso,
            'has_error': bool(aviso),
        }}

    def _reservar(self, session, data, flow_token):
        if not session.partner_id:
            # No debería ocurrir (CONFIRMAR se alcanza con partner ya
            # vinculado); volver a IDENTIDAD sería una ruta backward. Cierre
            # limpio con ERROR_SESION.
            return self._error_sesion()
        try:
            prof_id, dt_iso = (data.get('slot_id') or '|').split('|')
            prof_id = int(prof_id)
        except ValueError:
            # slot_id malformado a mitad de flujo → ERROR_SESION (la entrada
            # SERVICIO no admite aristas entrantes en el routing de Meta).
            return self._error_sesion()
        servicio = self._resolver_servicio(session, data.get('servicio_code'))
        _ROBADO = ('⚠️ Ese horario ya no está disponible. Toca *Atrás* '
                   'y elige otra hora.')
        if not self._resolver_operador(session, servicio, prof_id):
            # prof_id echoed inválido/ajeno/no-operador: mismo tratamiento
            # que un hueco robado (no revelamos por qué).
            return self._confirmar_con_error(session, data, _ROBADO)
        Primitives = self.env['innatum.agenda.scheduling.primitives']
        # `reserve_directo` atrapa la excepción de solape internamente y
        # devuelve {'error': ...} sin relanzar, pero el turno inválido que
        # intentó crear queda "sucio" (ya insertado/recompute pendiente) en
        # la misma transacción. Si no deshacemos ese estado, la próxima
        # consulta (p.ej. el Turno.search de _screen_hora al recalcular las
        # horas) vuelve a disparar la misma ValidationError al hacer flush.
        # El savepoint aísla el intento fallido y lo revierte por completo.
        with self.env.cr.savepoint() as sp:
            res = Primitives.reserve_directo(
                prof_id, dt_iso, servicio_code=data.get('servicio_code'),
                partner_id=session.partner_id.id,
                company=session.company_id)
            if res.get('error'):
                sp.close(rollback=True)
        if res.get('error'):
            # Hueco robado / inválido: refrescar CONFIRMAR con aviso (no se
            # puede navegar de vuelta a HORA por routing).
            return self._confirmar_con_error(session, data, _ROBADO)
        turno_id = res.get('turno_id') or res.get('id') or 0
        return {'screen': 'SUCCESS', 'data': {
            'extension_message_response': {'params': {
                'flow_token': flow_token,
                'turno_id': turno_id,
            }}}}

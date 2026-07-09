# -*- coding: utf-8 -*-
"""Cola de mensajes salientes de WhatsApp (Fase 1 — canal proactivo).

Odoo construye el body Meta completo y lo encola aquí; un dispatcher lo
envía al workflow n8n `AGENDA-WF-Outbound`, que resuelve el token del
tenant en Supabase y llama a la API Graph. Los tokens de Meta nunca se
guardan en Odoo. Spec: docs/superpowers/specs/
2026-07-03-fase1-canal-saliente-whatsapp-design.md
"""
import logging
import threading
from datetime import timedelta

import requests

from odoo import _, api, fields, models
from odoo.tools import str2bool

_logger = logging.getLogger(__name__)

# Backoff en minutos entre reintentos: 1m, 5m, 15m, 1h, 6h (~7,4h en total)
BACKOFF_MINUTES = [1, 5, 15, 60, 360]
# Reintentos tras el primer fallo (6 envíos en total)
MAX_RETRIES = 5
# Minutos tras los que un registro en 'sending' se considera atascado
# (worker muerto con el POST en vuelo) y se devuelve a la cola.
STALE_SENDING_MINUTES = 15


class InnatumWaOutbound(models.Model):
    _name = 'innatum.wa.outbound'
    _description = 'Cola de mensajes salientes de WhatsApp'
    _order = 'create_date desc, id desc'

    company_id = fields.Many2one(
        'res.company', string='Tenant', required=True, index=True,
        help='Compañía emisora: de aquí sale el phone_number_id con el que '
             'n8n resuelve el token del tenant en Supabase.',
    )
    to_number = fields.Char(
        string='Destinatario', required=True,
        help='Número destino en formato Meta (5939XXXXXXXX).',
    )
    category = fields.Selection([
        ('derivacion_colaborador', 'Derivación a colaborador'),
        ('derivacion_paciente', 'Derivación: aviso al paciente'),
        ('aviso_agenda', 'Aviso de agenda'),
        ('prueba', 'Prueba'),
    ], string='Categoría', default='prueba', required=True,
       help='Origen funcional del mensaje, para auditoría y métricas.')
    meta_payload = fields.Json(
        string='Payload Meta', required=True,
        help='Body completo del mensaje para la API Graph de Meta. n8n lo '
             'envía tal cual: agregar tipos de mensaje nuevos no requiere '
             'tocar el workflow.',
    )
    state = fields.Selection([
        ('pending', 'Pendiente'),
        ('sending', 'Enviando'),
        ('sent', 'Enviado'),
        ('failed', 'Fallido'),
        ('cancelled', 'Cancelado'),
    ], string='Estado', default='pending', required=True, index=True)
    attempts = fields.Integer(string='Intentos fallidos', default=0)
    next_attempt_at = fields.Datetime(
        string='Próximo intento',
        help='Vacío = elegible de inmediato. Con valor = backoff en curso.',
    )
    wamid = fields.Char(
        string='WAMID', readonly=True,
        help='ID del mensaje devuelto por Meta al confirmar el envío.',
    )
    error_message = fields.Text(string='Último error', readonly=True)
    res_model = fields.Char(
        string='Modelo de origen',
        help='Registro que originó el mensaje (p.ej. la derivación), para '
             'trazabilidad y notas en su chatter.',
    )
    res_id = fields.Integer(string='ID de origen')

    # ------------------------------------------------------------------
    # Normalización de números
    # ------------------------------------------------------------------

    @api.model
    def normalize_ec_number(self, raw):
        """Normaliza un celular ecuatoriano al formato Meta (5939XXXXXXXX).

        Acepta: '09XXXXXXXX', '9XXXXXXXX', '5939XXXXXXXX' (con o sin '+',
        espacios o guiones). Devuelve False si no es un celular EC válido
        (fijos, números cortos y basura se rechazan).
        """
        if not raw:
            return False
        digits = ''.join(ch for ch in str(raw) if ch.isdigit())
        if digits.startswith('5939') and len(digits) == 12:
            return digits
        if digits.startswith('09') and len(digits) == 10:
            return '593' + digits[1:]
        if digits.startswith('9') and len(digits) == 9:
            return '593' + digits
        return False

    # ------------------------------------------------------------------
    # API de encolado
    # ------------------------------------------------------------------

    @api.model
    def queue_template(self, company, to_number, template_name, variables,
                       origin=None, category='prueba', buttons=None):
        """Encola una plantilla de WhatsApp para el tenant `company`.

        Construye el body Meta completo (idioma 'es'). `buttons` es una
        lista opcional de payloads para los botones quick-reply definidos
        en la plantilla Meta (mismo orden); el tap vuelve por el Gateway
        como texto con ese payload (p.ej. 'st_deriv:45'). Devuelve el
        registro creado, o un recordset vacío si el número no es un
        celular EC válido (el llamador decide cómo degradar).
        """
        to = self.normalize_ec_number(to_number)
        if not to:
            _logger.warning(
                'WA outbound: número inválido %r (tenant %s, plantilla %s)',
                to_number, company.name, template_name)
            return self.browse()
        # Debe coincidir EXACTO con el idioma de aprobación de las
        # plantillas en Meta (p.ej. es_EC); si difiere, Meta responde
        # #132001 'Template name does not exist in the translation'.
        lang = (self.env['ir.config_parameter'].sudo().get_param(
            'innatum_wa.template_lang') or 'es').strip() or 'es'
        components = [{
            'type': 'body',
            'parameters': [
                {'type': 'text', 'text': str(v)} for v in variables
            ],
        }]
        for idx, btn_payload in enumerate(buttons or []):
            components.append({
                'type': 'button',
                'sub_type': 'quick_reply',
                'index': str(idx),
                'parameters': [
                    {'type': 'payload', 'payload': btn_payload},
                ],
            })
        payload = {
            'messaging_product': 'whatsapp',
            'to': to,
            'type': 'template',
            'template': {
                'name': template_name,
                'language': {'code': lang},
                'components': components,
            },
        }
        rec = self.sudo().create({
            'company_id': company.id,
            'to_number': to,
            'category': category,
            'meta_payload': payload,
            'res_model': origin._name if origin else False,
            'res_id': origin.id if origin else False,
        })
        rec._schedule_dispatch()
        return rec

    def _schedule_dispatch(self):
        """Dispara el cron del dispatcher tras el commit de esta transacción.

        `ir.cron._trigger()` es post-commit por diseño: si la transacción
        que encoló hace rollback, no se envía nada. Tolera que el cron aún
        no exista (instalaciones a medio actualizar).
        """
        cron = self.env.ref(
            'innatum_agenda_ai.ir_cron_wa_outbound_dispatch',
            raise_if_not_found=False)
        if cron:
            cron.sudo()._trigger()

    # ------------------------------------------------------------------
    # Dispatcher
    # ------------------------------------------------------------------

    @api.model
    def _dispatch_pending(self, limit=20):
        """Envía los mensajes pendientes elegibles al webhook n8n outbound.

        Corre desde el cron (cada 5 min) y desde el trigger post-commit del
        encolado. Devuelve la cantidad de mensajes enviados con éxito.
        """
        icp = self.env['ir.config_parameter'].sudo()
        if not str2bool(
                icp.get_param('innatum_wa.outbound_enabled') or 'False', False):
            return 0
        url = icp.get_param('innatum_wa.outbound_webhook_url')
        secret = icp.get_param('innatum_wa.outbound_shared_secret')
        if not url or not secret:
            _logger.warning(
                'WA outbound habilitado pero sin webhook_url/shared_secret; '
                'no se envía nada.')
            return 0
        now = fields.Datetime.now()
        # Recuperar mensajes atascados en 'sending' (worker muerto con el
        # POST en vuelo). Riesgo asumido: si el envío original sí llegó,
        # puede duplicarse el mensaje — preferible a perderlo en silencio.
        stale = self.sudo().search([
            ('state', '=', 'sending'),
            ('write_date', '<', now - timedelta(minutes=STALE_SENDING_MINUTES)),
        ])
        if stale:
            _logger.warning(
                'WA outbound: %s mensaje(s) atascados en "sending" (ids %s); '
                'se devuelven a la cola.', len(stale), stale.ids)
            for rec in stale:
                rec.write({'state': 'pending', 'attempts': rec.attempts + 1})
        pending = self.sudo().search([
            ('state', '=', 'pending'),
            '|', ('next_attempt_at', '=', False),
                 ('next_attempt_at', '<=', now),
        ], limit=limit, order='create_date, id')
        # En tests no se debe comitear (cursor de savepoint); en producción
        # sí, para que un crash a mitad de lote no re-envíe lo ya enviado.
        auto_commit = not getattr(threading.current_thread(), 'testing', False)
        sent = 0
        for rec in pending:
            if not rec.company_id.wa_phone_number_id:
                rec._register_failure(
                    'El tenant no tiene wa_phone_number_id configurado',
                    retryable=False)
                if auto_commit:
                    self.env.cr.commit()
                continue
            rec.write({'state': 'sending'})
            if auto_commit:
                self.env.cr.commit()
            if rec._send_to_gateway(url, secret):
                sent += 1
            if auto_commit:
                self.env.cr.commit()
        return sent

    def _send_to_gateway(self, url, secret):
        """POST de este registro al webhook n8n. Devuelve True si quedó
        enviado; en fallo registra el error (backoff o failed) y devuelve
        False. Nunca lanza excepción de red."""
        self.ensure_one()
        try:
            resp = requests.post(
                url,
                json={
                    'phone_number_id': self.company_id.wa_phone_number_id,
                    'to': self.to_number,
                    'payload': self.meta_payload,
                },
                headers={'X-Innatum-Outbound-Token': secret},
                timeout=30,
            )
        except requests.RequestException as exc:
            self._register_failure(str(exc), retryable=True)
            return False
        if resp.status_code != 200:
            self._register_failure(
                'HTTP %s del webhook n8n' % resp.status_code, retryable=True)
            return False
        try:
            data = resp.json() or {}
        except ValueError:
            self._register_failure(
                'Respuesta no-JSON del webhook n8n', retryable=True)
            return False
        if data.get('ok'):
            self.write({
                'state': 'sent',
                'wamid': data.get('wamid') or False,
                'error_message': False,
                'next_attempt_at': False,
            })
            self._notify_origin(_(
                'Notificación WhatsApp enviada a %s.') % self.to_number)
            return True
        self._register_failure(
            data.get('error') or 'Error desconocido de Meta',
            retryable=bool(data.get('retryable')))
        return False

    def _register_failure(self, error, retryable):
        """Registra un fallo: reprograma con backoff o marca `failed`."""
        self.ensure_one()
        attempts = self.attempts + 1
        vals = {'attempts': attempts, 'error_message': error}
        if retryable and attempts <= MAX_RETRIES:
            delay = BACKOFF_MINUTES[attempts - 1]
            vals.update(
                state='pending',
                next_attempt_at=fields.Datetime.now()
                + timedelta(minutes=delay))
        else:
            vals.update(state='failed', next_attempt_at=False)
        self.write(vals)
        if vals['state'] == 'failed':
            _logger.error('WA outbound %s FALLIDO hacia %s: %s',
                          self.id, self.to_number, error)
            self._notify_origin(_(
                'No se pudo enviar la notificación WhatsApp a %(to)s: '
                '%(err)s') % {'to': self.to_number, 'err': error})

    def _notify_origin(self, body):
        """Deja una nota en el chatter del registro de origen (si lo hay)."""
        self.ensure_one()
        if not self.res_model or not self.res_id \
                or self.res_model not in self.env:
            return
        record = self.env[self.res_model].sudo().browse(self.res_id).exists()
        if record and hasattr(record, 'message_post'):
            try:
                record.message_post(body=body)
            except Exception:  # pragma: no cover - el chatter nunca rompe el envío
                _logger.warning(
                    'WA outbound %s: no se pudo anotar el chatter de %s,%s',
                    self.id, self.res_model, self.res_id)

    # ------------------------------------------------------------------
    # Acciones de la vista
    # ------------------------------------------------------------------

    def action_requeue(self):
        """Re-encola a mano los mensajes fallidos (auditoría backend)."""
        fallidos = self.filtered(lambda r: r.state == 'failed')
        fallidos.write({
            'state': 'pending',
            'attempts': 0,
            'next_attempt_at': False,
            'error_message': False,
        })
        if fallidos:
            fallidos[0]._schedule_dispatch()
        return True

    def action_cancel_message(self):
        """Cancela a mano mensajes que aún no salieron (pending/failed)."""
        self.filtered(lambda r: r.state in ('pending', 'failed')).write({
            'state': 'cancelled',
            'next_attempt_at': False,
        })
        return True

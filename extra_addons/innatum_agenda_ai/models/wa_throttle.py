# -*- coding: utf-8 -*-
"""Modelo para rate-limiting y cooldown anti-abuso de mensajes WhatsApp.

Tres mecanismos protegen contra desperdicio de tokens y abuso:

  1. Rate limit: máximo N mensajes por ventana móvil de M minutos desde un
     mismo wa_from + tenant.
  2. Cooldown progresivo: tras N expiraciones (ej. 3 fallos consecutivos de
     cédula), el wa_from queda en pausa por X horas. Reincidencias dentro
     de 24h escalan a 24h.
  3. Aviso single-shot: durante un cooldown activo, solo el primer mensaje
     del cliente recibe la respuesta plantilla; los siguientes se silencian
     (skip_send) para no spamear.
"""
from datetime import datetime, timedelta
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


# Constantes de configuración (alineadas con la decisión de diseño).
RATE_LIMIT_MAX_MESSAGES = 30
RATE_LIMIT_WINDOW_MIN = 60
COOLDOWN_FIRST_HOURS = 2
COOLDOWN_REPEAT_HOURS = 24
COOLDOWN_REPEAT_WINDOW_HOURS = 24


class WaThrottle(models.Model):
    _name = 'innatum.wa.throttle'
    _description = 'WhatsApp throttle: rate-limit y cooldown por wa_from'
    _rec_name = 'wa_from'

    wa_from = fields.Char(required=True, index=True)
    company_id = fields.Many2one('res.company', required=True, index=True)

    # Rate limit (ventana móvil de mensajes)
    rate_window_start = fields.Datetime(
        help='Inicio de la ventana actual para conteo de mensajes.',
    )
    rate_message_count = fields.Integer(default=0)

    # Cooldown
    expirations_24h = fields.Integer(
        default=0,
        help='Contador de expiraciones por cédula fallida en las últimas 24h.',
    )
    last_expiration_at = fields.Datetime()
    cooldown_until = fields.Datetime(
        help='Si está en el futuro, el wa_from está en pausa.',
    )
    cooldown_notified = fields.Boolean(
        default=False,
        help='Si ya enviamos el aviso de cooldown al cliente en esta ventana.',
    )

    _sql_constraints = [
        ('unique_wa_company',
         'unique(wa_from, company_id)',
         'Ya existe un registro de throttle para este wa_from + tenant.'),
    ]

    # -------------------------------------------------------------------------
    # API pública (usada por process_message)
    # -------------------------------------------------------------------------

    @api.model
    def get_or_create_for(self, wa_from, company):
        """Devuelve el record para (wa_from, company), creando si no existe."""
        rec = self.search([
            ('wa_from', '=', wa_from),
            ('company_id', '=', company.id),
        ], limit=1)
        if rec:
            return rec
        return self.create({
            'wa_from': wa_from,
            'company_id': company.id,
        })

    def check_and_consume_rate(self):
        """Verifica rate-limit y consume +1 si pasa.

        Returns:
          (allowed: bool, remaining: int)
        """
        self.ensure_one()
        now = datetime.utcnow()
        window_size = timedelta(minutes=RATE_LIMIT_WINDOW_MIN)
        if (not self.rate_window_start
                or (now - self.rate_window_start) >= window_size):
            # Nueva ventana
            self.rate_window_start = now
            self.rate_message_count = 1
            return True, RATE_LIMIT_MAX_MESSAGES - 1
        if self.rate_message_count >= RATE_LIMIT_MAX_MESSAGES:
            return False, 0
        self.rate_message_count = self.rate_message_count + 1
        return True, RATE_LIMIT_MAX_MESSAGES - self.rate_message_count

    def is_in_cooldown(self):
        """Devuelve (in_cooldown: bool, until: datetime|None)."""
        self.ensure_one()
        if not self.cooldown_until:
            return False, None
        now = datetime.utcnow()
        if self.cooldown_until > now:
            return True, self.cooldown_until
        return False, None

    def mark_cooldown_notified(self):
        """Marca que ya avisamos al cliente del cooldown."""
        self.ensure_one()
        self.cooldown_notified = True

    def record_expiration(self):
        """Registra una expiración por 3-fail-cédula y aplica cooldown.

        Regla:
          - 1ra expiración (o tras >24h de la última) → cooldown 2h.
          - 2da o más expiraciones dentro de 24h → cooldown 24h.
        """
        self.ensure_one()
        now = datetime.utcnow()
        repeat_window = timedelta(hours=COOLDOWN_REPEAT_WINDOW_HOURS)
        within_window = (
            self.last_expiration_at
            and (now - self.last_expiration_at) <= repeat_window
        )
        if within_window:
            self.expirations_24h = (self.expirations_24h or 0) + 1
        else:
            # Empieza una nueva ventana de 24h
            self.expirations_24h = 1
        self.last_expiration_at = now
        # Decidir duración del cooldown
        if self.expirations_24h >= 2:
            hours = COOLDOWN_REPEAT_HOURS
        else:
            hours = COOLDOWN_FIRST_HOURS
        self.cooldown_until = now + timedelta(hours=hours)
        self.cooldown_notified = False
        _logger.info(
            'wa_throttle: %s cooldown %sh (expirations=%s)',
            self.wa_from, hours, self.expirations_24h,
        )
        return self.cooldown_until

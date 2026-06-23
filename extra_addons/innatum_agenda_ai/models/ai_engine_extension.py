# -*- coding: utf-8 -*-
"""Hook al motor IA: agrega gate por saldo de recargas IA del tenant.

El motor genérico (innatum.ai.engine) tiene su propio gate por límite
mensual/conversación. Acá agregamos un gate adicional: si la company
actual tiene una suscripción y su saldo de recargas IA llegó a 0,
bloqueamos la llamada con un mensaje útil para el admin del tenant.

Si el módulo de planes NO está instalado, este hook no existe y el
engine genérico sigue funcionando sin cambios.
"""

import logging

from odoo import models, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AIEngineExtension(models.AbstractModel):
    _inherit = 'innatum.ai.engine'

    @api.model
    def _is_chatbot_available_for_company(self, company):
        """Override: el chatbot solo aparece si la company tiene saldo IA.

        Delega al modelo de suscripción que sabe de recargas. Si la
        company no tiene suscripción (caso: My Company del sistema),
        retorna False — el chatbot NO se renderiza en el sitio público.
        """
        Sus = self.env['in_agenda.suscripcion'].sudo()
        return Sus._has_ai_credit_for_company(company)

    def _check_cost_limits(self, provider, conversation=None):
        # Primero el chequeo estándar del engine (límite mensual + conversación)
        super()._check_cost_limits(provider, conversation=conversation)

        # El gate solo aplica a COMPANIES con suscripción (tenants).
        # Si la company del context NO tiene suscripción, asumimos que
        # es la company del sistema (My Company) o un caller técnico —
        # bypass.
        #
        # NOTA: NO chequear `user.has_group('base.group_system')` porque
        # los controllers del chatbot público llaman con sudo() y eso
        # convertiría a `self.env.user` en admin, bypaseando el gate
        # para tenants reales (bug crítico de cobranza).
        company = self.env.company
        if not company:
            return

        Sus = self.env['in_agenda.suscripcion'].sudo()
        susc = Sus._get_for_company(company)
        if not susc:
            # Sin suscripción activa para esta company.
            # Caso normal: My Company (sistema) — Innatum admin probando.
            # Caso anómalo: tenant sin provisioning correcto — bug operativo,
            # se loguea para detectar pero NO se bloquea (para no romper
            # testing de Innatum desde su company).
            _logger.info(
                'AI gate: company %s (id=%s) sin suscripción — bypass.',
                company.name, company.id,
            )
            return

        # Si el add-on IA web no está vigente hoy en la suscripción, bloquear
        if not susc._has_feature('ia_web'):
            raise UserError(
                'Tu suscripción no tiene la IA web activada. '
                'Contacta a Innatum para habilitarla.'
            )

        # Si no hay recargas (caso típico de tenant nuevo), bloqueo amable
        if not susc.recarga_ids:
            raise UserError(
                'No tienes recargas de IA activas. Contacta a Innatum para '
                'cargar saldo y empezar a usar el asistente.'
            )

        # Saldo agotado
        if susc.tokens_restantes_total_usd <= 0:
            _logger.info(
                'AI gate: company %s sin saldo (recargas=%s, restante=%.4f)',
                company.name, len(susc.recarga_ids),
                susc.tokens_restantes_total_usd,
            )
            raise UserError(
                'Sin saldo de IA disponible. Las recargas se agotaron. '
                'Contacta a Innatum para recargar tu saldo y seguir usando '
                'el asistente.'
            )

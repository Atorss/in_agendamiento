# -*- coding: utf-8 -*-
import uuid
from odoo import models, fields, api


class ChatbotSession(models.Model):
    _name = 'innatum.ai.chatbot.session'
    _description = 'Sesión de chatbot web'
    _order = 'create_date desc'

    token = fields.Char('Token', required=True, index=True, default=lambda self: uuid.uuid4().hex)
    company_id = fields.Many2one(
        'res.company', string='Empresa', required=True, index=True,
        default=lambda self: self.env.company,
        help='Tenant del website donde se inició la sesión. Determina '
             'qué turnos/profesionales/servicios puede ver el chatbot.',
    )
    provider_id = fields.Many2one('innatum.ai.provider', string='Proveedor IA', required=True, ondelete='restrict')
    api_messages = fields.Text('Historial API (JSON)', default='[]')
    message_count = fields.Integer('Mensajes enviados', default=0)
    state = fields.Selection([
        ('pending_id', 'Esperando identificación'),
        ('pending_register', 'Registro de cliente'),
        ('active', 'Activa'),
        ('done', 'Completada'),
        ('limit', 'Límite alcanzado'),
    ], string='Estado', default='pending_id')

    turno_id = fields.Many2one('innatum.agenda.turno', string='Turno reservado')
    partner_id = fields.Many2one('res.partner', string='Cliente identificado')
    register_vat = fields.Char('Cédula pendiente de registro')

    MAX_MESSAGES = 40

    @api.autovacuum
    def _gc_old_sessions(self):
        """Limpia sesiones inactivas de más de 7 días."""
        limit_date = fields.Datetime.subtract(fields.Datetime.now(), days=7)
        self.search([('create_date', '<', limit_date)]).unlink()

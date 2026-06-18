# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class InnatumAgendaServicio(models.Model):
    """Catálogo centralizado de servicios del SaaS.

    Los servicios son gestionados por Innatum (catálogo global) y se asignan
    a uno o más tenants vía company_ids (M2M). El admin del tenant solo VE
    los servicios que Innatum le habilitó; no puede crear ni editar.

    Esto garantiza consistencia cross-tenant: el código "CORTE" significa
    "Corte de pelo" en TODOS los tenants que lo ofrecen, simplificando
    analytics, chatbot IA y onboarding (Innatum tilda servicios al
    provisionar un tenant nuevo).
    """
    _name = 'innatum.agenda.servicio'
    _description = 'Servicio (catálogo)'
    _order = 'name'

    name = fields.Char(string='Nombre', required=True)
    code = fields.Char(string='Código', required=True)
    description = fields.Text(string='Descripción')
    active = fields.Boolean(default=True)

    company_ids = fields.Many2many(
        'res.company',
        'innatum_agenda_servicio_company_rel',
        'servicio_id', 'company_id',
        string='Tenants habilitados',
        help='Tenants (companies) que pueden ofrecer este servicio. '
             'Innatum decide qué servicios habilita para cada tenant.',
    )

    _sql_constraints = [
        ('code_unique', 'unique(code)',
         'El código del servicio debe ser único en el catálogo.'),
    ]

    def unlink(self):
        if not self.env.user.has_group(
            'innatum_agenda_core.innatum_agenda_group_admin'
        ) and not self.env.user.has_group('base.group_system'):
            raise ValidationError(
                "Los servicios del catálogo solo pueden ser eliminados "
                "por administradores Innatum."
            )
        return super().unlink()
